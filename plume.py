"""Plume — local voice dictation for Windows, web-glass UI.

Native core (audio, engine, global hotkey, paste, tray) in Python; the UI is an
embedded web view (pywebview). This is a taskbar app with a compact native
window, tray icon and a floating listening bubble.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
import webview

from sttlocal import DictationEngine, Recorder, clean_transcript, copy_text, paste_text
from config import Config, config_dir, hotkey_to_pynput, debug_log as _debug_log
from vocabulary import Vocabulary


# UI 'profile' value -> (backend, device)
PROFILES = {
    "fw-cpu": ("faster-whisper", "cpu"),
    "ov-npu": ("openvino", "NPU"),
    "ov-gpu": ("openvino", "GPU"),
    "ov-cpu": ("openvino", "CPU"),
}
FAST_WHISPER_MODEL_NAMES = {"base", "small", "medium", "turbo"}
DEFAULT_OPENVINO_MODEL = r"models\openvino\whisper-small"
APP_VERSION = "1.2.0"
GITHUB_REPO_URL = "https://github.com/hugoinformatique/Plume"
GITHUB_RELEASES_URL = "https://api.github.com/repos/hugoinformatique/Plume/releases/latest"
GITHUB_RELEASES_LATEST_URL = f"{GITHUB_REPO_URL}/releases/latest"
INSTALLER_RE = re.compile(r"^Plume-Setup-(?P<version>\d+(?:\.\d+)+)\.exe$", re.IGNORECASE)
AUTO_UPDATE_MAX_BYTES = 200 * 1024 * 1024  # above this, ask before downloading
# Live preview cadence. The delay before the first snapshot keeps very short
# dictations from paying for a preview nobody will read; the tail bounds the
# cost of each one so a long dictation does not get progressively slower.
LIVE_PREVIEW_FIRST_S = 1.6
LIVE_PREVIEW_EVERY_S = 1.4
LIVE_PREVIEW_TAIL_S = 7.0


def resource_dir() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def ui_file(name: str) -> str:
    return os.path.join(resource_dir(), "ui", name)


def set_autostart(enable: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import winreg
        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE)
        if enable and getattr(sys, "frozen", False):
            winreg.SetValueEx(key, "Plume", 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            try:
                winreg.DeleteValue(key, "Plume")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


def version_key(version: str) -> tuple[int, ...]:
    """Return a comparable numeric version tuple from 'v0.4.22' or '0.4.22'."""
    cleaned = version.strip().lower().lstrip("v")
    return tuple(int(part) for part in re.findall(r"\d+", cleaned))


def _release_via_redirect() -> dict:
    """Latest release without touching the REST API.

    api.github.com allows 60 unauthenticated calls per hour *per IP* -- easily
    exhausted on a shared/corporate connection, and the app then reported
    "rate limit exceeded" and refused to update at all. github.com itself has
    no such quota: /releases/latest simply redirects to /releases/tag/vX.Y.Z,
    and the installer asset name is deterministic (INSTALLER_RE), so the whole
    check can be done with one redirect.
    """
    response = requests.get(
        GITHUB_RELEASES_LATEST_URL,
        headers={"User-Agent": f"Plume/{APP_VERSION}"},
        timeout=8,
        allow_redirects=True,
    )
    response.raise_for_status()
    match = re.search(r"/releases/tag/(?P<tag>[^/?#]+)", response.url)
    if not match:
        raise RuntimeError(f"tag introuvable dans {response.url}")
    tag = match.group("tag")
    latest_version = tag.lstrip("v")
    asset = f"Plume-Setup-{latest_version}.exe"
    return {
        "available": version_key(latest_version) > version_key(APP_VERSION),
        "current_version": APP_VERSION,
        "latest_version": latest_version,
        "tag_name": tag,
        "release_url": response.url,
        "asset_name": asset,
        "asset_size": None,
        "download_url": f"{GITHUB_REPO_URL}/releases/download/{tag}/{asset}",
    }


def latest_release_info() -> dict:
    try:
        response = requests.get(
            GITHUB_RELEASES_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"Plume/{APP_VERSION}",
            },
            timeout=8,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        # 403/429 = quota; anything else may be a proxy filtering the API host.
        # Either way the redirect route is worth a try before giving up.
        _debug_log(f"release API unavailable ({exc}); trying the redirect route")
        return _release_via_redirect()
    release = response.json()
    tag = str(release.get("tag_name") or "")
    latest_version = tag.lstrip("v") or APP_VERSION
    installer = None
    for asset in release.get("assets", []):
        name = str(asset.get("name") or "")
        if INSTALLER_RE.match(name):
            installer = asset
            break
    if installer is None:
        return {
            "available": False,
            "current_version": APP_VERSION,
            "latest_version": latest_version,
            "message": "Aucun installeur Plume trouvé sur la dernière release.",
        }
    return {
        "available": version_key(latest_version) > version_key(APP_VERSION),
        "current_version": APP_VERSION,
        "latest_version": latest_version,
        "tag_name": tag,
        "release_url": release.get("html_url"),
        "asset_name": installer.get("name"),
        "asset_size": installer.get("size"),
        "download_url": installer.get("browser_download_url"),
    }


def resolve_model_path(model: str) -> Path:
    """Absolute location of an OpenVINO model directory.

    A relative path (the default `models\\openvino\\whisper-small`) can mean
    two things: a model the user converted next to the app, or the one shipped
    inside the installer. Look next to the working directory first, then in the
    bundle (`sys._MEIPASS` when frozen), and always hand the engine an absolute
    path so it cannot resolve it differently than this check did.
    """
    path = Path(model or "")
    if path.is_absolute():
        return path
    for base in (Path.cwd(), Path(resource_dir())):
        candidate = base / path
        if candidate.exists():
            return candidate
    return Path.cwd() / path


def profile_blocker(profile: str, model: str) -> str | None:
    """Why this profile cannot run here, in French, or None if it can.

    The OpenVINO profiles (NPU / iGPU / OpenVINO-CPU) need the `openvino-genai`
    runtime and a model *converted* to the OpenVINO IR format. Since v0.4.25
    the installer ships both, so this normally passes -- but a run from source
    (or a build without them) must not let the UI persist a config the engine
    will then fail to load at every start, an unrecoverable state from inside
    the app. Refuse up front and say what is missing instead.
    """
    if not profile.startswith("ov-"):
        return None
    import importlib.util

    if importlib.util.find_spec("openvino_genai") is None:
        return ("Ce profil demande le moteur OpenVINO, absent de cette installation. "
                "Installe-le (requirements-openvino.txt) puis convertis un modèle "
                "avant de le sélectionner.")
    path = resolve_model_path(model)
    if not path.exists():
        return (f"Modèle OpenVINO introuvable : {path}. Convertis-en un "
                "(optimum-cli export openvino …) puis indique son dossier.")
    return None


def parse_combo_keys(combo: str) -> set:
    """'<ctrl>+<space>' -> {Key.ctrl, KeyCode(vk=space)}.

    Delegates to pynput's own HotKey.parse -- it returns modifiers as Key and
    every other key as a vk-based KeyCode, which is exactly the normalised
    form Listener.canonical() produces, so parsed combos compare equal to
    live key events (ctrl_l/ctrl_r both canonicalise to ctrl).

    Raises ValueError on an unparseable combo; callers validate *before*
    tearing down a working listener.
    """
    from pynput import keyboard

    return set(keyboard.HotKey.parse(combo))


class HotkeyEngine:
    """One raw keyboard listener driving both hotkey modes.

    Previously toggle mode used pynput's GlobalHotKeys and push-to-talk used a
    separate raw listener. Two code paths meant two sets of failure modes --
    and a GlobalHotKeys instance whose stop() didn't take effect kept the old
    shortcut alive after a change. Here a single listener tracks raw key state
    and fires on *transitions*:

      - hold=False: on_activate() once when the combo becomes complete
        (edge-triggered, so OS key-repeat cannot double-fire it),
      - hold=True: on_activate() when complete, on_deactivate() as soon as any
        key of the combo is released.
    """

    def __init__(self, combo: str, on_activate, on_deactivate=None, hold: bool = False) -> None:
        self.combo = combo
        self.hold = hold
        self._keys = parse_combo_keys(combo)  # may raise: validate at build time
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate
        self._pressed: set = set()
        self._active = False
        self._listener = None

    def start(self) -> None:
        """Start the listener and wait (briefly) for its message loop to exist.

        pynput's Listener.wait() is an unbounded Condition.wait(): if the
        backend fails while setting up (no display on a dev machine, hook
        refused), the thread dies without ever marking itself ready and wait()
        never returns -- which would hang the caller while it holds the hotkey
        lock. Bound it, then check the listener is actually alive.
        """
        from pynput import keyboard

        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        waiter = threading.Thread(target=self._listener.wait, daemon=True)
        waiter.start()
        waiter.join(2.0)
        if waiter.is_alive() or not self._listener.running:
            self.stop()
            raise RuntimeError("écouteur clavier indisponible (hook refusé par le système)")

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
        self._pressed.clear()
        self._active = False

    def _canonical(self, key):
        listener = self._listener
        if listener is None:
            return key
        try:
            return listener.canonical(key)
        except Exception:
            return key

    def _modifiers(self) -> set:
        """The four modifier keys, canonicalised (ctrl_l and ctrl_r -> ctrl)."""
        from pynput import keyboard

        return {keyboard.Key.ctrl, keyboard.Key.alt, keyboard.Key.shift, keyboard.Key.cmd}

    def _matches(self) -> bool:
        """Combo complete, and no *extra* modifier held.

        A plain subset test is not enough once there are two shortcuts: with
        Ctrl+Shift+Space held, {ctrl, space} is a subset of what is pressed, so
        the dictation shortcut fired at the same time as the translation one --
        and the debounce in toggle() then swallowed whichever came second, so
        the mode you got was a race. It also means Ctrl+Alt+Space no longer
        triggers a Ctrl+Space shortcut, which was never intended either.
        """
        if not self._keys.issubset(self._pressed):
            return False
        try:
            extra = (self._pressed & self._modifiers()) - self._keys
        except Exception:  # pragma: no cover - pynput unavailable
            return True
        return not extra

    def _on_press(self, key) -> None:
        self._pressed.add(self._canonical(key))
        if not self._active and self._matches():
            self._active = True
            _debug_log(f"hotkey fired: {self.combo} ({'hold' if self.hold else 'toggle'})")
            try:
                self._on_activate()
            except Exception as exc:  # noqa: BLE001 - never kill the listener thread
                _debug_log(f"hotkey callback error: {exc}")

    def _on_release(self, key) -> None:
        self._pressed.discard(self._canonical(key))
        if self._active and not self._matches():
            self._active = False
            if self.hold and self._on_deactivate is not None:
                _debug_log(f"hotkey released: {self.combo}")
                try:
                    self._on_deactivate()
                except Exception as exc:  # noqa: BLE001
                    _debug_log(f"hotkey callback error: {exc}")


class PlumeApp:
    def __init__(self) -> None:
        self.config = Config.load()
        self.vocab = Vocabulary(self.config.get("vocabulary", []))
        self.recorder = Recorder()
        self.engine: DictationEngine | None = None
        self._engine_key: tuple | None = None
        self.engine_lock = threading.Lock()
        self.window = None
        self.bubble = None
        self.tray = None
        self.hotkeys = None
        self._hotkey_lock = threading.Lock()
        self._beep_lock = threading.Lock()
        self.recording = False
        self.worker: threading.Thread | None = None
        self._level_stop = threading.Event()
        self._last_toggle_at = 0.0
        self.recordings_dir = config_dir() / "recordings"
        self._update_info: dict | None = None
        # "transcribe" or "translate", armed per dictation by the shortcut used.
        self._task = "transcribe"
        self.hotkeys_translate = None
        # One engine, one inference at a time: the live preview and the final
        # pass share the same warm pipeline.
        self._infer_lock = threading.Lock()

    # ---- engine (kept warm) -------------------------------------------------
    def _engine_params(self) -> tuple:
        c = self.config
        return (c.get("backend"), c.get("model"), c.get("device"),
                c.get("compute"), c.get("language"))

    def _get_engine(self) -> DictationEngine:
        backend, model, device, compute, language = self._engine_params()
        key = (backend, model, device, compute, language)
        with self.engine_lock:
            if self.engine is None or key != self._engine_key:
                lang = None if str(language).lower() == "auto" else language
                if backend == "openvino":
                    # Hand the backend the same absolute directory the
                    # availability check validated -- it resolves plain
                    # Path(model) against the working directory, which is not
                    # where the bundled model lives in a frozen build.
                    model = str(resolve_model_path(model))
                engine = DictationEngine(model_name=model, device=device,
                                         compute_type=compute, language=lang, backend=backend)
                try:
                    engine.load()
                except BaseException as exc:  # noqa: BLE001
                    # The shipping engine is the Intel Arc iGPU. profile_blocker
                    # only proves the runtime and the model files are present --
                    # it cannot know whether *this* machine actually has a
                    # usable iGPU, and that only shows up here, as a failed
                    # load. Dictation must still work on such a machine, so
                    # degrade to the CPU engine instead of leaving the user with
                    # an error and no way back (the engine picker is gone).
                    if backend != "openvino":
                        raise
                    _debug_log(f"openvino {device} unusable ({type(exc).__name__}: {exc}), "
                               "falling back to the CPU engine")
                    engine = self._cpu_fallback_engine(lang)
                    key = self._engine_params()
                self.engine = engine
                self._engine_key = key
            return self.engine

    def _cpu_fallback_engine(self, lang) -> DictationEngine:
        """faster-whisper on CPU, persisted so the next start goes straight there."""
        backend, device = PROFILES["fw-cpu"]
        c = self.config
        c.data["backend"], c.data["device"] = backend, device
        c.data["model"] = "small"
        c.save()
        engine = DictationEngine(model_name="small", device=device,
                                 compute_type=c.get("compute"), language=lang,
                                 backend=backend)
        engine.load()
        self._set_status("Accélération iGPU indisponible sur ce PC : moteur CPU activé.", "Prêt")
        return engine

    def _preload(self) -> None:
        self._set_status("Chargement du modèle…", "…")
        try:
            self._get_engine()
            self._set_status("Prêt à dicter", "Prêt")
        except BaseException as exc:  # noqa: BLE001
            # BaseException on purpose: openvino's import helper calls
            # sys.exit() when it cannot find its own DLL directory, and a bare
            # `except Exception` left the app stuck on "Chargement du modèle…"
            # forever with nothing on screen.
            _debug_log(f"engine load FAILED: {type(exc).__name__}: {exc}")
            self._set_status(f"Erreur moteur : {exc}", "Erreur")

    # ---- JS bridge ----------------------------------------------------------
    def _js(self, window, code: str) -> None:
        try:
            if window is not None:
                window.evaluate_js(code)
        except Exception:
            pass

    def _set_status(self, text: str, mini: str = "") -> None:
        self._js(self.window, f"window.plume && plume.setStatus({json.dumps(text)}, {json.dumps(mini)})")

    def _set_recording_ui(self, on: bool) -> None:
        self._js(self.window, f"window.plume && plume.setRecording({str(on).lower()})")

    def _set_transcript(self, text: str) -> None:
        self._js(self.window, f"window.plume && plume.setTranscript({json.dumps(text)})")

    def _set_history(self) -> None:
        history = self.config.get("history", [])
        self._js(self.window, f"window.plume && plume.setHistory({json.dumps(history)})")

    def _set_update_ui(self, info: dict) -> None:
        self._js(self.window, f"window.plume && plume.setUpdate({json.dumps(info)})")

    # ---- floating bubble ----------------------------------------------------
    def _get_bubble(self):
        """The listening pill, created on first use.

        It used to be a second pywebview window (frameless + transparent +
        always-on-top): three releases in a row it simply never appeared on
        the user's machine, which is a known weak spot of that combination on
        Windows/EdgeChromium. It is now a native Tk window (floating_bubble.py)
        driven from any thread, so its lifecycle no longer depends on the web
        view at all.
        """
        if self.bubble is None:
            try:
                from floating_bubble import FloatingBubble

                saved = self.config.get("bubble_xy")
                self.bubble = FloatingBubble(
                    position=self.config.get("bubble_position") or "bottom",
                    pos=tuple(saved) if isinstance(saved, (list, tuple)) and len(saved) == 2 else None,
                    on_move=self._save_bubble_position,
                )
            except Exception as exc:  # noqa: BLE001
                _debug_log(f"bubble unavailable: {type(exc).__name__}: {exc}")
                return None
        return self.bubble

    def _save_bubble_position(self, x: int, y: int) -> None:
        # The user dragged it somewhere: that is where it belongs from now on.
        self.config.set("bubble_xy", [int(x), int(y)])

    def _bubble_state(self, state: str, text: str) -> None:
        bubble = self._get_bubble()
        if bubble is not None:
            bubble.set_state(state, text)

    def _preview_label(self, text: str, fallback: str) -> str:
        """What the pill shows once the text has landed.

        With the preview on, that is the transcript itself -- the point of the
        feature is to confirm what was just inserted without looking away from
        the document being written. The pill grows to fit and ellipsizes from
        the left, so the *end* of the sentence stays readable.
        """
        if not self.config.get("bubble_preview"):
            return fallback
        flat = " ".join(str(text).split())
        return flat or fallback

    def _bubble_done(self, text: str, full: str = "") -> None:
        """Closing beat of a dictation: a brief confirmation on the pill.

        The longer the text, the longer it stays up -- a 40-word paragraph
        flashed for the same 950 ms as "Collé" is unreadable.
        """
        if self.bubble is not None:
            try:
                length = len(full or text)
                ms = 950 if not full else max(950, min(2600, 700 + 26 * length))
                self.bubble.flash_done(text, ms)
            except Exception as exc:  # noqa: BLE001
                _debug_log(f"bubble flash_done failed: {exc}")

    def _show_bubble(self, listening: bool) -> None:
        bubble = self._get_bubble()
        if bubble is None:
            return
        bubble.position = self.config.get("bubble_position") or "bottom"
        bubble.show("listening" if listening else "transcribing",
                    "À l'écoute…" if listening else "Transcription…")

    def _hide_bubble(self) -> None:
        if self.bubble is not None:
            try:
                self.bubble.hide()
            except Exception as exc:  # noqa: BLE001
                _debug_log(f"bubble hide failed: {exc}")

    def _level_loop(self) -> None:
        bubble = self.bubble
        while not self._level_stop.is_set() and self.recording:
            lvl = self.recorder.current_level()
            if bubble is not None:
                bubble.set_level(lvl)
            time.sleep(0.07)

    # ---- recording ----------------------------------------------------------
    def toggle_translate(self) -> None:
        """Dictate in French, insert English. Same flow, Whisper's other task.

        Arming the mode only makes sense when a dictation *starts*: pressing
        the translate shortcut while already recording means "stop", exactly
        like the normal one, and must not retarget a dictation in flight.
        """
        if not self.recording:
            self._task = "translate"
        self.toggle()

    def toggle(self) -> None:
        # The global hotkey (often Ctrl+Space) can fire twice for one press
        # -- e.g. OS key-repeat on the space bar if it's held a fraction too
        # long -- which used to start and immediately stop the recording,
        # showing the listening bubble for a single frame before hiding it
        # again. Debounce it.
        now = time.perf_counter()
        if now - self._last_toggle_at < 0.6:
            return
        self._last_toggle_at = now
        if self.worker and self.worker.is_alive():
            return
        if self.recording:
            self._stop()
        else:
            self._start()

    # ---- push-to-talk ---------------------------------------------------
    def _ptt_press(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.recording:
            self._start()

    def _ptt_release(self) -> None:
        if self.recording:
            self._stop()

    def _beep(self, kind: str) -> None:
        """Short audio cue on start/stop, independent of the bubble.

        Fired on its own thread: playback is synchronous and would otherwise
        delay the actual start of the capture (and, on stop, the WAV flush).
        """
        if not self.config.get("sound_feedback"):
            return
        threading.Thread(target=self._beep_now, args=(kind,), daemon=True).start()

    def _beep_now(self, kind: str) -> None:
        # Played through the sound card with sounddevice -- the same audio
        # stack the recorder already uses, so if dictation works the cue is
        # audible. winsound.Beep drives the (emulated) motherboard speaker,
        # which is silent on a lot of machines: that is why v0.4.23 still had
        # no sound. winsound stays as a fallback.
        try:
            import sounddevice as sd

            # Use the output device's own sample rate rather than forcing
            # 44100: the resampling that WASAPI does otherwise is what made
            # the cue sound gritty. Two separate tones spliced together were
            # also audible as a stutter -- one clean note per event instead.
            rate = 48000
            try:
                default_out = sd.default.device[1]
                info = sd.query_devices(default_out, "output")
                rate = int(info["default_samplerate"]) or rate
            except Exception:  # noqa: BLE001 - fall back to 48 kHz
                pass
            freq = 1046.5 if kind == "start" else 659.25  # C6 up, E5 down
            wave = self._tone(freq, 0.11, rate) * 0.25
            with self._beep_lock:
                sd.stop()  # never let two cues overlap into a warble
                sd.play(wave, samplerate=rate, blocking=True)
            return
        except Exception as exc:  # noqa: BLE001
            _debug_log(f"beep via sounddevice failed ({kind}): {exc}")
        if sys.platform != "win32":
            return
        try:
            import winsound
            freq, dur_ms = (988, 130) if kind == "start" else (587, 130)
            winsound.Beep(freq, dur_ms)
        except Exception as exc:  # noqa: BLE001
            _debug_log(f"beep via winsound failed ({kind}): {exc}")
            try:
                import winsound
                winsound.MessageBeep(
                    winsound.MB_ICONASTERISK if kind == "start" else winsound.MB_OK
                )
            except Exception as exc2:  # noqa: BLE001
                _debug_log(f"MessageBeep fallback failed ({kind}): {exc2}")

    @staticmethod
    def _tone(freq: float, seconds: float, rate: int):
        """A sine with raised-cosine edges -- a raw square start/stop would
        click, which is exactly the kind of cheap detail you hear."""
        import numpy as np

        count = max(2, int(rate * seconds))
        t = np.linspace(0.0, seconds, count, endpoint=False)
        wave = np.sin(2.0 * np.pi * freq * t).astype("float32")
        # Long-ish raised-cosine attack and a decay over most of the note: a
        # short hard edge clicks, and a flat sine that stops dead sounds like a
        # glitch rather than a cue.
        attack = max(1, min(int(rate * 0.012), count // 2))
        ramp = ((1.0 - np.cos(np.linspace(0.0, np.pi, attack))) / 2.0).astype("float32")
        wave[:attack] *= ramp
        decay = max(1, min(int(rate * 0.06), count - attack))
        fade = ((1.0 + np.cos(np.linspace(0.0, np.pi, decay))) / 2.0).astype("float32")
        wave[count - decay:] *= fade
        return wave

    def _live_preview_loop(self) -> None:
        """Transcribe short snapshots while the user speaks, to fill the bubble.

        This is only worth doing because of *when* it happens: during a
        dictation the engine is idle -- the real pass does not start until the
        user stops -- so the iGPU is free. Two rules keep it from ever costing
        the user anything that matters:

        - the final transcription holds `_infer_lock` and always wins; a
          preview that cannot take the lock is skipped, not queued;
        - snapshots only cover the last few seconds, so their cost stays flat
          however long the dictation runs.
        """
        time.sleep(LIVE_PREVIEW_FIRST_S)
        while self.recording:
            if not self.config.get("bubble_preview"):
                return
            path = None
            acquired = self._infer_lock.acquire(blocking=False)
            if acquired:
                try:
                    path = self.recorder.snapshot_to_wav(
                        self.recordings_dir, tail_seconds=LIVE_PREVIEW_TAIL_S
                    )
                    if path is not None and self.recording:
                        engine = self._get_engine()
                        result = engine.transcribe_full(path, task=self._task)
                        text = " ".join(str(result.text).split())
                        if text and self.recording:
                            bubble = self.bubble
                            if bubble is not None:
                                bubble.set_text(text)
                except Exception as exc:  # noqa: BLE001
                    # A preview is a nicety: log it and stop trying, never let
                    # it surface as an error over a working dictation.
                    _debug_log(f"live preview stopped: {type(exc).__name__}: {exc}")
                    return
                finally:
                    self._infer_lock.release()
                    if path is not None:
                        try:
                            path.unlink(missing_ok=True)
                        except Exception:
                            pass
            time.sleep(LIVE_PREVIEW_EVERY_S)

    def _start(self) -> None:
        self.recording = True
        if self.bubble is not None or self._task == "translate":
            bubble = self._get_bubble()
            if bubble is not None:
                bubble.set_translate(self._task == "translate")
        self.recorder.start()
        self._beep("start")
        self._set_recording_ui(True)
        self._show_bubble(listening=True)
        self._level_stop.clear()
        threading.Thread(target=self._level_loop, daemon=True).start()
        if self.config.get("bubble_preview"):
            threading.Thread(target=self._live_preview_loop, daemon=True).start()

    def _stop(self) -> None:
        self.recording = False
        self._level_stop.set()
        self._beep("stop")
        self._set_recording_ui(False)
        path = self.recorder.stop_to_wav(self.recordings_dir)
        if path is None:
            self._set_status("Enregistrement trop court", "Prêt")
            self._hide_bubble()
            return
        translating = self._task == "translate"
        self._bubble_state("transcribing", "Traduction…" if translating else "Transcription…")
        self._set_status("Traduction locale…" if translating else "Transcription locale…", "…")
        self.worker = threading.Thread(target=self._transcribe, args=(path,), daemon=True)
        self.worker.start()

    def _transcribe(self, path: Path) -> None:
        flashed = False
        task, self._task = self._task, "transcribe"
        try:
            engine = self._get_engine()
            hotwords = self.vocab.hotwords() or None
            initial = self.vocab.initial_prompt() or None
            with self._infer_lock:
                result = engine.transcribe_full(
                    path, hotwords=hotwords, initial_prompt=initial, task=task
                )
            mode = self.config.get("cleanup")
            # Spoken punctuation and layout commands are French; on a
            # translated pass the output is English, so cleaning it with the
            # French command list would mangle it.
            if task == "translate":
                text = result.text.strip()
            else:
                text = result.text if mode == "off" else clean_transcript(result.text, mode)
            text = self.vocab.apply(text)
            self._set_transcript(text)
            if text:
                self._add_history(text)
            if text and self.config.get("autopaste"):
                paste_text(text)
                self._set_status(f"Collé — {result.elapsed:.1f}s", "Prêt")
                self._bubble_done(self._preview_label(text, "Collé"), text)
                flashed = True
            elif text:
                copy_text(text)
                self._set_status(f"Prêt (copié) — {result.elapsed:.1f}s", "Prêt")
                self._bubble_done(self._preview_label(text, "Copié"), text)
                flashed = True
            else:
                self._set_status("Aucun texte détecté", "Prêt")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Erreur : {exc}", "Erreur")
        finally:
            # The wav is only ever needed for this one transcription; the
            # text (not the audio) is what's kept in history. Delete it
            # right away instead of letting recordings/ grow unbounded.
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            # A confirmation flash hides the bubble itself once it has been
            # on screen long enough to read; hiding here too would cut it off.
            if not flashed:
                time.sleep(0.5)
                self._hide_bubble()

    def _cleanup_old_recordings(self, max_age_hours: float = 24.0) -> None:
        """Best-effort sweep for wav files that outlived their transcription
        (e.g. the app crashed mid-run before the per-file cleanup above ran).
        Runs at startup so leftover recordings never silently accumulate."""
        cutoff = time.time() - max_age_hours * 3600
        for folder in (self.recordings_dir,):
            try:
                if not folder.exists():
                    continue
                for f in folder.glob("*.wav"):
                    try:
                        if f.stat().st_mtime < cutoff:
                            f.unlink()
                    except OSError:
                        pass
            except Exception:
                pass

    def _add_history(self, text: str) -> None:
        item = {
            "text": text,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        history = [item]
        for old in self.config.get("history", []):
            if old.get("text") != text:
                history.append(old)
            if len(history) >= 12:
                break
        self.config.set("history", history)
        self._set_history()

    # ---- hotkey -------------------------------------------------------------
    def _restart(self, engine: "HotkeyEngine | None") -> bool:
        """Re-arm a previously working engine after a failed rebind."""
        if engine is None:
            return False
        try:
            clone = HotkeyEngine(
                engine.combo, engine._on_activate, engine._on_deactivate, hold=engine.hold
            )
            clone.start()
        except Exception as exc:  # noqa: BLE001
            _debug_log(f"hotkey restore FAILED: combo={engine.combo} err={exc}")
            return False
        self.hotkeys = clone
        _debug_log(f"hotkey restored: combo={engine.combo} mode={'hold' if engine.hold else 'toggle'}")
        return True

    def _install_hotkey(self) -> dict:
        """(Re)bind the global shortcut. Returns {"ok", "error"} so the UI can
        tell the user when a combination could not be registered instead of
        silently keeping the previous one."""
        combo = self.config.get("hotkey") or "<ctrl>+<space>"
        hold = bool(self.config.get("push_to_talk"))
        mode = "push-to-talk" if hold else "toggle"
        with self._hotkey_lock:
            # Build (and therefore validate the combo) *before* tearing down the
            # working listener: a typo used to leave the app with no shortcut at
            # all, or with the old one still bound.
            try:
                engine = HotkeyEngine(
                    combo,
                    on_activate=(lambda: threading.Thread(target=self._ptt_press, daemon=True).start())
                    if hold else
                    (lambda: threading.Thread(target=self.toggle, daemon=True).start()),
                    on_deactivate=lambda: threading.Thread(target=self._ptt_release, daemon=True).start(),
                    hold=hold,
                )
            except Exception as exc:  # noqa: BLE001
                _debug_log(f"hotkey build FAILED: combo={combo} mode={mode} err={exc}")
                self._set_status(f"Raccourci invalide : {exc}", "")
                return {"ok": False, "error": f"Raccourci invalide : {exc}"}

            old, self.hotkeys = self.hotkeys, None
            if old is not None:
                try:
                    old.stop()
                except Exception as exc:  # noqa: BLE001
                    _debug_log(f"hotkey stop of previous listener failed: {exc}")
            try:
                engine.start()
            except Exception as exc:  # noqa: BLE001
                _debug_log(f"hotkey install FAILED: combo={combo} mode={mode} err={exc}")
                # Never leave the app with no shortcut at all: put the previous
                # listener back (a fresh instance -- a stopped pynput listener
                # cannot be restarted).
                restored = self._restart(old)
                self._set_status(f"Raccourci indisponible : {exc}", "")
                return {
                    "ok": False,
                    "error": f"Raccourci indisponible : {exc}",
                    "restored": restored,
                }
            self.hotkeys = engine
        _debug_log(f"hotkey installed: combo={combo} mode={mode}")
        self._set_status(f"Raccourci actif : {self.config.get('hotkey_display')}", "Prêt")
        self._install_translate_hotkey()
        return {"ok": True, "error": None}

    def _install_translate_hotkey(self) -> dict:
        """(Re)bind the translation shortcut. Always toggle, never push-to-talk.

        A failure here is not fatal the way the main shortcut is: dictation
        still works, only the translate mode is unavailable. It is reported,
        not raised, and it never touches `self.hotkeys`.
        """
        with self._hotkey_lock:
            old, self.hotkeys_translate = self.hotkeys_translate, None
            if old is not None:
                try:
                    old.stop()
                except Exception as exc:  # noqa: BLE001
                    _debug_log(f"translate hotkey stop failed: {exc}")

            combo = str(self.config.get("hotkey_translate") or "").strip()
            if not combo or not self.config.get("translate_enabled"):
                _debug_log("translate hotkey disabled")
                return {"ok": True, "error": None, "enabled": False}
            if combo == (self.config.get("hotkey") or ""):
                # Two listeners on one combination: whichever answers first
                # wins, so the mode would be a coin toss.
                message = "Le raccourci de traduction doit différer du raccourci de dictée."
                _debug_log(f"translate hotkey refused: identical to the dictation one ({combo})")
                return {"ok": False, "error": message, "enabled": False}
            try:
                engine = HotkeyEngine(
                    combo,
                    on_activate=lambda: threading.Thread(
                        target=self.toggle_translate, daemon=True).start(),
                    on_deactivate=lambda: None,
                    hold=False,
                )
                engine.start()
            except Exception as exc:  # noqa: BLE001
                _debug_log(f"translate hotkey install FAILED: combo={combo} err={exc}")
                return {"ok": False, "error": f"Raccourci de traduction indisponible : {exc}",
                        "enabled": False}
            self.hotkeys_translate = engine
        _debug_log(f"translate hotkey installed: combo={combo}")
        return {"ok": True, "error": None, "enabled": True}

    # ---- tray ---------------------------------------------------------------
    def _tray_image(self):
        from ui_theme import make_icon_image
        from PIL import Image
        assets = Path(resource_dir()) / "assets" / "plume.png"
        try:
            if assets.exists():
                return Image.open(assets).convert("RGBA")
        except Exception:
            pass
        return make_icon_image(64)

    def _start_tray(self) -> None:
        try:
            import pystray
            def ev(fn):
                return lambda icon=None, item=None: fn()
            menu = pystray.Menu(
                pystray.MenuItem("Afficher Plume", ev(self.show_window), default=True),
                pystray.MenuItem("Démarrer / Arrêter", ev(self.toggle)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quitter", ev(self.quit)),
            )
            self.tray = pystray.Icon("Plume", self._tray_image(), "Plume", menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception:
            pass

    # ---- window controls (called from JS) -----------------------------------
    def show_window(self) -> None:
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass

    # ---- updates -----------------------------------------------------------
    def _auto_update_check(self) -> None:
        """Startup check that installs the update by itself -- unless it is a
        heavy one.

        Now that the installer carries the OpenVINO runtime and a converted
        model, it weighs hundreds of MB. Pulling that down unannounced at every
        launch following a release is not something to do to someone's
        connection: above the threshold we only surface the update bar and let
        them press the button.
        """
        info = self.check_for_update(notify=True)
        if not info.get("available"):
            return
        size = info.get("asset_size") or 0
        # An *unknown* size counts as too big: the redirect route (used exactly
        # when GitHub's API is rate-limited) cannot report one, and that must
        # not become the loophole through which a 350 MB installer downloads
        # itself unannounced.
        if not size or size > AUTO_UPDATE_MAX_BYTES:
            weight = f" ({size / (1024 * 1024):.0f} Mo)" if size else ""
            _debug_log(f"update {info.get('latest_version')}{weight}: waiting for a click")
            self._set_update_ui({
                **info,
                "message": f"Mise à jour {info.get('latest_version')} disponible{weight} — "
                           "clique sur « Mettre à jour » quand tu veux.",
            })
            return
        self._download_and_launch_update()

    def check_for_update(self, notify: bool = True) -> dict:
        try:
            info = latest_release_info()
            self._update_info = info if info.get("available") else None
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            message = f"Recherche de mise à jour impossible : {exc}"
            if "404" in text:
                message = "Release GitHub inaccessible. Le dépôt Plume est probablement privé."
            elif "403" in text or "429" in text or "rate limit" in text.lower():
                message = (f"GitHub limite temporairement les requêtes. Réessaie plus tard, "
                           f"ou télécharge l'installeur : {GITHUB_RELEASES_LATEST_URL}")
            _debug_log(f"update check failed: {exc}")
            info = {
                "available": False,
                "current_version": APP_VERSION,
                "latest_version": APP_VERSION,
                "message": message,
            }
        if notify:
            self._set_update_ui(info)
        return info

    def _download_and_launch_update(self) -> None:
        info = self._update_info or self.check_for_update(notify=False)
        if not info.get("available") or not info.get("download_url"):
            self._set_update_ui({
                "available": False,
                "current_version": APP_VERSION,
                "latest_version": APP_VERSION,
                "message": "Plume est déjà à jour.",
            })
            return
        try:
            self._set_update_ui({**info, "installing": True, "message": "Téléchargement de la mise à jour…"})
            update_dir = Path(tempfile.gettempdir()) / "PlumeUpdate"
            update_dir.mkdir(parents=True, exist_ok=True)
            dest = update_dir / str(info["asset_name"])
            part = dest.with_suffix(dest.suffix + ".part")
            with requests.get(
                str(info["download_url"]),
                headers={"User-Agent": f"Plume/{APP_VERSION}"},
                stream=True,
                timeout=30,
            ) as response:
                response.raise_for_status()
                with part.open("wb") as fh:
                    for chunk in response.iter_content(chunk_size=1024 * 512):
                        if chunk:
                            fh.write(chunk)
            part.replace(dest)
            self._set_update_ui({**info, "installing": True, "message": "Installation en cours…"})
            # No /CLOSEAPPLICATIONS: that flag makes the installer ask
            # Windows' Restart Manager to close *us* -- but we'd be sitting
            # in proc.wait() below, not processing that request, so the
            # installer's close attempt fails ("impossible de fermer
            # l'application") and the update never completes. We close
            # ourselves instead, immediately, which unlocks our own exe for
            # the installer to overwrite.
            # The installer runs *visibly*, and Inno's own postinstall entry
            # ("Lancer Plume", `skipifsilent`) puts the app back up afterwards.
            #
            # It used to run /SILENT, which meant nothing could relaunch us --
            # so we spawned a detached, hidden-window PowerShell to wait on the
            # installer and start the app again. That is textbook EDR bait
            # (unsigned binary spawns hidden PowerShell that launches another
            # binary) for a convenience worth a few seconds, on a machine whose
            # security review we are asking someone to sign off. Showing the
            # installer is also simply more honest about what is happening.
            subprocess.Popen([str(dest), "/NORESTART"])
            time.sleep(0.3)
            self.quit()
        except Exception as exc:  # noqa: BLE001
            self._set_update_ui({**info, "installing": False, "message": f"Mise à jour impossible : {exc}"})

    # ---- lifecycle ----------------------------------------------------------
    def _on_started(self) -> None:
        self._start_tray()
        self._install_hotkey()
        set_autostart(bool(self.config.get("autostart")))
        self._repair_profile()
        threading.Thread(target=self._preload, daemon=True).start()
        threading.Thread(target=self._cleanup_old_recordings, daemon=True).start()
        # Opt-in only. Out of the box Plume opens no outbound connection at
        # all: the update check runs when the user enables it, or when they
        # press "Vérifier". That is the claim the security review is given, so
        # it has to hold at the only place that could break it.
        if self.config.get("auto_update"):
            threading.Thread(target=self._auto_update_check, daemon=True).start()

    def _repair_profile(self) -> None:
        """Fall back to the CPU profile if the stored one cannot run here.

        Before v0.4.24 the UI happily saved an OpenVINO profile even without
        the runtime or a converted model. The engine then failed to load at
        *every* start, and the only way out was to guess which setting had
        poisoned the config. Fix it on the spot and say so.
        """
        c = self.config
        profile = next(
            (k for k, v in PROFILES.items() if v == (c.get("backend"), c.get("device"))),
            "fw-cpu",
        )
        blocker = profile_blocker(profile, str(c.get("model") or ""))
        if not blocker:
            return
        _debug_log(f"profile {profile} unusable at startup, falling back to fw-cpu: {blocker}")
        backend, device = PROFILES["fw-cpu"]
        c.data["backend"], c.data["device"] = backend, device
        if str(c.get("model") or "").startswith("models\\openvino\\"):
            c.data["model"] = "small"
        c.save()
        self._set_status("Profil NPU/iGPU indisponible : retour au moteur CPU.", "Prêt")

    def quit(self) -> None:
        for listener in (self.hotkeys, self.hotkeys_translate):
            try:
                if listener:
                    listener.stop()
            except Exception:
                pass
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        try:
            if self.bubble is not None:
                self.bubble.shutdown()
        except Exception:
            pass
        try:
            if self.window is not None:
                self.window.destroy()
        except Exception:
            pass

    def run(self) -> None:
        api = Api(self)
        self.window = _create_window(
            "Plume", ui_file("index.html"), js_api=api,
            width=420, height=700, resizable=True, frameless=False,
            easy_drag=False, min_size=(400, 620), hidden=True,
        )
        # The bubble is a native Tk window created on first dictation (see
        # _get_bubble) instead of here, so self.bubble starts as None
        # (already set in __init__).
        webview.start(self._on_started, debug=False)
        # start() returns when the last web view closes -- which is not
        # necessarily through our quit(). Tear the rest down explicitly so the
        # tray icon, the hotkey hook and the bubble's Tk loop don't outlive it.
        self.quit()


def _create_window(title, url, **kwargs):
    """create_window that tolerates pywebview versions lacking some kwargs."""
    try:
        return webview.create_window(title, url, **kwargs)
    except TypeError:
        for opt in ("focus", "min_size", "easy_drag", "transparent", "background_color"):
            kwargs.pop(opt, None)
        return webview.create_window(title, url, **kwargs)


# Api methods whose arguments carry text the user typed or dictated. debug.log
# is a support artefact that gets sent around by mail and read by third
# parties, and the deployment security file states it holds no dictated or
# user-authored text -- so these are logged by shape, never by value.
_REDACTED_API_ARGS = {"add_word"}


def _loggable_args(name: str, args: tuple) -> str:
    if name in _REDACTED_API_ARGS:
        return f"(<{len(args)} argument(s) masqué(s)>)"
    return repr(args)


def _api_call(fn):
    """Every UI action goes through here: it lands in debug.log and always
    answers the UI with a serialisable {"ok": ...} object.

    Until now an exception raised inside an Api method surfaced as a rejected
    promise that the UI dropped on the floor, so a failing action was
    indistinguishable from a working one -- the symptom being "the app shows
    the change but nothing happens"."""

    def wrapper(self, *args, **kwargs):
        _debug_log(f"api {fn.__name__}{_loggable_args(fn.__name__, args)}")
        try:
            result = fn(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            _debug_log(f"api {fn.__name__} FAILED: {type(exc).__name__}: {exc}")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(result, dict):
            result.setdefault("ok", True)
            result.setdefault("error", None)
            return result
        return result if result is not None else {"ok": True, "error": None}

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class Api:
    """Methods exposed to the web UI as window.pywebview.api.*

    The app reference is deliberately private: pywebview walks the js_api
    object with dir() and exposes every callable it finds, recursing into
    public attributes. A public `self.app` therefore published hundreds of
    nested methods to page JS (`app.quit`, `app.config.path.unlink`, ...) and
    made the bridge injection -- which enumerates them all before firing
    `pywebviewready` -- measurably slower to become usable.
    """

    def __init__(self, app: PlumeApp) -> None:
        self._app = app

    @_api_call
    def ping(self):
        """Bridge liveness probe, called by the UI on startup."""
        return {"ok": True, "version": APP_VERSION}

    def _current_profile(self) -> str:
        c = self._app.config
        return next(
            (k for k, v in PROFILES.items() if v == (c.get("backend"), c.get("device"))),
            "fw-cpu",
        )

    @_api_call
    def get_state(self):
        c = self._app.config
        profile = self._current_profile()
        return {
            "words": self._app.vocab.to_list(),
            "history": c.get("history", []),
            "app_version": APP_VERSION,
            "config": {
                "language": c.get("language"), "model": c.get("model"),
                "profile": profile, "cleanup": c.get("cleanup"),
                "compute": c.get("compute"), "bubble_position": c.get("bubble_position"),
                "hotkey_display": c.get("hotkey_display"),
                "hotkey_translate_display": c.get("hotkey_translate_display"),
                "translate_enabled": c.get("translate_enabled"),
                "bubble_preview": c.get("bubble_preview"),
                "autopaste": c.get("autopaste"), "autostart": c.get("autostart"),
                "push_to_talk": c.get("push_to_talk"), "sound_feedback": c.get("sound_feedback"),
                "auto_update": c.get("auto_update"),
            },
            "bridge": True,
        }

    @_api_call
    def toggle(self):
        self._app.toggle()

    @_api_call
    def add_word(self, heard, correct):
        self._app.vocab.add(heard, correct)
        return {"ok": self._app.config.set("vocabulary", self._app.vocab.to_list())}

    @_api_call
    def remove_word(self, index):
        self._app.vocab.remove(int(index))
        return {"ok": self._app.config.set("vocabulary", self._app.vocab.to_list())}

    @_api_call
    def paste_history(self, index):
        history = self._app.config.get("history", [])
        try:
            text = history[int(index)]["text"]
        except Exception:
            return {"ok": False, "error": "Entrée d'historique introuvable"}
        paste_text(text)
        self._app._set_status("Historique recollé", "Prêt")

    @_api_call
    def copy_history(self, index):
        history = self._app.config.get("history", [])
        try:
            text = history[int(index)]["text"]
        except Exception:
            return {"ok": False, "error": "Entrée d'historique introuvable"}
        copy_text(text)
        self._app._set_status("Historique copié", "Prêt")

    @_api_call
    def clear_history(self):
        """Wipe the stored dictations.

        The history is the one place where the text the user dictated sits at
        rest, in clear, in config.json. A deployment security review asks what
        can purge it; without this the only answer was "edit the JSON by hand".
        """
        ok = self._app.config.set("history", [])
        self._app._set_history()
        return {"ok": ok}

    @_api_call
    def set_hotkey(self, display):
        """Persist the new shortcut, then rebind it. The rebind is what the UI
        confirms on: a combination that can be displayed is not necessarily one
        pynput can register."""
        combo = hotkey_to_pynput(display)
        previous_display = self._app.config.get("hotkey_display")
        previous_combo = self._app.config.get("hotkey")
        self._app.config.data["hotkey_display"] = display
        saved = self._app.config.set("hotkey", combo)
        installed = self._app._install_hotkey()
        if not installed.get("ok"):
            # Roll back to what is actually bound, so the UI and the real
            # shortcut can never drift apart.
            self._app.config.data["hotkey_display"] = previous_display
            self._app.config.set("hotkey", previous_combo)
            self._app._install_hotkey()
            return {
                "ok": False, "error": installed.get("error"),
                "hotkey_display": previous_display, "combo": previous_combo,
            }
        if not saved:
            # The shortcut *is* armed -- reporting a failure here would make
            # the UI revert to a label that no longer matches reality. Warn
            # instead: it is the persistence that failed, not the binding.
            return {
                "ok": True, "hotkey_display": display, "combo": combo,
                "warning": "Raccourci actif, mais non enregistré : écriture de config.json impossible (voir debug.log)",
            }
        return {"ok": True, "hotkey_display": display, "combo": combo}

    @_api_call
    def set_translate_hotkey(self, display):
        """Same contract as set_hotkey, for the FR->EN shortcut."""
        combo = hotkey_to_pynput(display)
        previous_display = self._app.config.get("hotkey_translate_display")
        previous_combo = self._app.config.get("hotkey_translate")
        self._app.config.data["hotkey_translate_display"] = display
        self._app.config.set("hotkey_translate", combo)
        installed = self._app._install_translate_hotkey()
        if not installed.get("ok"):
            self._app.config.data["hotkey_translate_display"] = previous_display
            self._app.config.set("hotkey_translate", previous_combo)
            self._app._install_translate_hotkey()
            return {
                "ok": False, "error": installed.get("error"),
                "hotkey_display": previous_display, "combo": previous_combo,
            }
        return {"ok": True, "hotkey_display": display, "combo": combo}

    @_api_call
    def set_setting(self, key, value):
        previous = self._current_profile() if key == "profile" else self._app.config.get(key)
        if key == "profile":
            backend, device = PROFILES.get(value, PROFILES["fw-cpu"])
            current_model = str(self._app.config.get("model") or "")
            if backend == "openvino" and current_model in FAST_WHISPER_MODEL_NAMES:
                current_model = DEFAULT_OPENVINO_MODEL
            elif backend == "faster-whisper" and current_model.startswith("models\\openvino\\"):
                current_model = "small"
            blocker = profile_blocker(str(value), current_model)
            if blocker:
                # Nothing written: the previous, working profile stays in place.
                _debug_log(f"profile {value} refused: {blocker}")
                self._app._set_status(blocker, "Indisponible")
                return {"ok": False, "key": key, "value": previous, "error": blocker}
            self._app.config.data["backend"] = backend
            self._app.config.data["device"] = device
            self._app.config.data["model"] = current_model
            saved = self._app.config.save()
            stored = value if self._app.config.verify("backend") == backend else None
        else:
            saved = self._app.config.set(key, value)
            stored = self._app.config.verify(key)
        if key in ("model", "profile", "compute", "language"):
            threading.Thread(target=self._app._preload, daemon=True).start()
        if key == "autostart":
            set_autostart(bool(value))
        if key == "translate_enabled":
            installed = self._app._install_translate_hotkey()
            if not installed.get("ok"):
                self._app.config.set(key, previous)
                return {"ok": False, "key": key, "value": previous,
                        "error": installed.get("error")}
        if key == "bubble_position":
            # Choosing top/bottom again means "put it back where you decide":
            # forget the position the user may have dragged it to, otherwise
            # the setting would silently have no effect.
            self._app.config.set("bubble_xy", None)
            if self._app.bubble is not None:
                self._app.bubble.position = value
                self._app.bubble.pos = None
        if key == "push_to_talk":
            # Synchronous: the answer tells the UI whether the mode is really
            # in effect, which is the whole point of the confirmation.
            installed = self._app._install_hotkey()
            if not installed.get("ok"):
                # The mode could not be armed -- put the stored value back so a
                # restart doesn't come up in a mode that never worked.
                self._app.config.set(key, previous)
                self._app._install_hotkey()
                return {"ok": False, "key": key, "value": previous, "error": installed.get("error")}
        if not saved:
            return {
                "ok": False, "key": key, "value": value,
                "error": "Écriture de config.json impossible (voir debug.log)",
            }
        # Read back from disk rather than trusting the in-memory dict: this is
        # what makes "the setting did not persist" detectable at the source.
        return {"ok": True, "key": key, "value": value, "stored": stored}

    @_api_call
    def reset_bubble_position(self):
        """Put the bubble back where the top/bottom setting says.

        Re-picking the same entry in a <select> fires no change event, so
        without this a bubble dragged somewhere unusable (off-screen corner,
        second monitor that is now unplugged) could not be brought back.
        """
        self._app.config.set("bubble_xy", None)
        if self._app.bubble is not None:
            self._app.bubble.pos = None
            self._app.bubble.position = self._app.config.get("bubble_position") or "bottom"
        return {"ok": True, "message": "Bulle replacée"}

    @_api_call
    def minimize(self):
        try:
            self._app.window.minimize()
        except Exception:
            try:
                self._app.window.hide()
            except Exception:
                pass

    @_api_call
    def hide_window(self):
        try:
            self._app.window.hide()
        except Exception:
            try:
                self._app.window.minimize()
            except Exception:
                pass

    @_api_call
    def quit(self):
        self._app.quit()

    @_api_call
    def check_update(self):
        return self._app.check_for_update(notify=True)

    @_api_call
    def install_update(self):
        threading.Thread(target=self._app._download_and_launch_update, daemon=True).start()
        return {"started": True}


# Kept alive for the process lifetime -- a named mutex is released as soon
# as its handle is closed/garbage-collected, which would defeat the point.
_single_instance_mutex = None


def _acquire_single_instance_lock() -> bool:
    """True if this is the only running instance. False if another one
    already holds the lock.

    Without this, launching Plume.exe a second time (easy to do by
    accident now that the app starts hidden in the tray with no window to
    remind you it's already running) starts a second process with its own
    independent copy of the config in memory. Both can write config.json,
    and only one of them actually wins the global hotkey registration --
    so settings changed in one instance can appear to "reset" (the other
    instance re-saves its stale copy), and hotkey-dependent features like
    push-to-talk can silently behave according to whichever instance
    happens to own the hotkey, not the one the user is looking at.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\PlumeSingleInstance")
        if not handle:
            return True  # couldn't even check -- fail open rather than block launching
        global _single_instance_mutex
        _single_instance_mutex = handle
        is_first = ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS
        _debug_log(f"single-instance check: {'first instance' if is_first else 'ANOTHER INSTANCE ALREADY RUNNING'}")
        return is_first
    except Exception as exc:  # noqa: BLE001
        _debug_log(f"single-instance check errored, failing open: {exc}")
        return True


def main() -> int:
    if sys.platform != "win32":
        print("Plume is Windows-first; the web UI can still open elsewhere for checks.")
    if not _acquire_single_instance_lock():
        print("Plume is already running (see the system tray).")
        return 0
    PlumeApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
