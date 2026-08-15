"""Plume — local voice dictation for Windows, web-glass UI.

Native core (audio, engine, global hotkey, paste, tray) in Python; the UI is an
embedded web view (pywebview). This is a taskbar app with a compact native
window, tray icon and a floating listening bubble.
"""

from __future__ import annotations

import csv
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
from config import Config, config_dir, hotkey_to_pynput
from vocabulary import Vocabulary
from backends import create_backend  # BENCHMARK MODE (temporary, remove after testing)


# UI 'profile' value -> (backend, device)
PROFILES = {
    "fw-cpu": ("faster-whisper", "cpu"),
    "ov-npu": ("openvino", "NPU"),
    "ov-gpu": ("openvino", "GPU"),
    "ov-cpu": ("openvino", "CPU"),
}
FAST_WHISPER_MODEL_NAMES = {"base", "small", "medium", "turbo"}
DEFAULT_OPENVINO_MODEL = r"models\openvino\whisper-small"
APP_VERSION = "0.4.9"
GITHUB_RELEASES_URL = "https://api.github.com/repos/hugoinformatique/Plume/releases/latest"
INSTALLER_RE = re.compile(r"^Plume-Setup-(?P<version>\d+(?:\.\d+)+)\.exe$", re.IGNORECASE)


# ==== BENCHMARK MODE (temporary, remove after testing) =======================
BENCH_CLIP_PATH = config_dir() / "benchmark-clip.wav"
BENCH_FW_MODELS = ["base", "small", "medium", "turbo"]
BENCH_FW_COMPUTE_TYPES = ["int8", "int8_float16", "float32"]
BENCH_OV_DEVICES = ["NPU", "GPU", "CPU"]


def discover_openvino_models() -> list[str]:
    """Any subfolder under models/openvino/ is assumed to be a converted
    OpenVINO IR model (see README "OpenVINO / NPU" / optimum-cli export)."""
    base = Path("models") / "openvino"
    if not base.exists():
        return []
    return [str(p) for p in sorted(base.iterdir()) if p.is_dir()]
# ==== /BENCHMARK MODE ==========================================================


def resource_dir() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def ui_file(name: str) -> str:
    return os.path.join(resource_dir(), "ui", name)


def screen_size() -> tuple[int, int]:
    if sys.platform == "win32":
        try:
            import ctypes
            u = ctypes.windll.user32
            return u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        except Exception:
            pass
    return 1920, 1080


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
    """Return a comparable numeric version tuple from 'v0.4.9' or '0.4.9'."""
    cleaned = version.strip().lower().lstrip("v")
    return tuple(int(part) for part in re.findall(r"\d+", cleaned))


def latest_release_info() -> dict:
    response = requests.get(
        GITHUB_RELEASES_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Plume/{APP_VERSION}",
        },
        timeout=8,
    )
    response.raise_for_status()
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
        self._hotkey = None
        self.recording = False
        self.worker: threading.Thread | None = None
        self._level_stop = threading.Event()
        self.metrics_path = config_dir() / "metrics.csv"
        self.recordings_dir = config_dir() / "recordings"
        self._update_info: dict | None = None
        # BENCHMARK MODE (temporary, remove after testing)
        self.bench_recorder = Recorder()
        self._bench_running = False

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
                engine = DictationEngine(model_name=model, device=device,
                                         compute_type=compute, language=lang, backend=backend)
                engine.load()
                self.engine = engine
                self._engine_key = key
            return self.engine

    def _preload(self) -> None:
        self._set_status("Chargement du modèle…", "…")
        try:
            self._get_engine()
            self._set_status("Prêt à dicter", "Prêt")
        except Exception as exc:  # noqa: BLE001
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

    def _bubble_state(self, state: str, text: str) -> None:
        self._js(self.bubble, f"window.plumeBubble && plumeBubble.setState({json.dumps(state)}, {json.dumps(text)})")

    def _set_update_ui(self, info: dict) -> None:
        self._js(self.window, f"window.plume && plume.setUpdate({json.dumps(info)})")

    # ---- bubble window ------------------------------------------------------
    def _place_bubble(self) -> None:
        if self.bubble is None:
            return
        sw, sh = screen_size()
        w, h = 252, 64
        x = (sw - w) // 2
        y = 56 if self.config.get("bubble_position") == "top" else sh - h - 96
        try:
            self.bubble.move(x, y)
        except Exception:
            pass

    def _show_bubble(self, listening: bool) -> None:
        if self.bubble is None:
            return
        self._place_bubble()
        try:
            self.bubble.show()
        except Exception:
            pass
        self._bubble_state("listening" if listening else "transcribing",
                           "À l'écoute…" if listening else "Transcription…")

    def _hide_bubble(self) -> None:
        if self.bubble is not None:
            try:
                self.bubble.hide()
            except Exception:
                pass

    def _level_loop(self) -> None:
        while not self._level_stop.is_set() and self.recording:
            lvl = self.recorder.current_level()
            self._js(self.bubble, f"window.plumeBubble && plumeBubble.setLevel({lvl:.3f})")
            time.sleep(0.07)

    # ---- recording ----------------------------------------------------------
    def toggle(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if self.recording:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        self.recording = True
        self.recorder.start()
        self._set_recording_ui(True)
        self._show_bubble(listening=True)
        self._level_stop.clear()
        threading.Thread(target=self._level_loop, daemon=True).start()

    def _stop(self) -> None:
        self.recording = False
        self._level_stop.set()
        self._set_recording_ui(False)
        path = self.recorder.stop_to_wav(self.recordings_dir)
        if path is None:
            self._set_status("Enregistrement trop court", "Prêt")
            self._hide_bubble()
            return
        self._bubble_state("transcribing", "Transcription…")
        self._set_status("Transcription locale…", "…")
        self.worker = threading.Thread(target=self._transcribe, args=(path,), daemon=True)
        self.worker.start()

    def _transcribe(self, path: Path) -> None:
        try:
            engine = self._get_engine()
            hotwords = self.vocab.hotwords() or None
            initial = self.vocab.initial_prompt() or None
            result = engine.transcribe_full(path, hotwords=hotwords, initial_prompt=initial)
            mode = self.config.get("cleanup")
            text = result.text if mode == "off" else clean_transcript(result.text, mode)
            text = self.vocab.apply(text)
            self._set_transcript(text)
            if text:
                self._add_history(text)
            self._log_metric(result, text)
            if text and self.config.get("autopaste"):
                paste_text(text)
                self._set_status(f"Collé — {result.elapsed:.1f}s", "Prêt")
            elif text:
                copy_text(text)
                self._set_status(f"Prêt (copié) — {result.elapsed:.1f}s", "Prêt")
            else:
                self._set_status("Aucun texte détecté", "Prêt")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Erreur : {exc}", "Erreur")
        finally:
            time.sleep(0.5)
            self._hide_bubble()

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

    def _log_metric(self, result, text: str) -> None:
        if not self.config.get("metrics"):
            return
        try:
            new = not self.metrics_path.exists()
            with self.metrics_path.open("a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(["timestamp", "backend", "device", "model", "audio_s",
                                "elapsed_s", "rtf", "chars", "vocab_terms"])
                backend, model, device, compute, language = self._engine_params()
                rtf = result.rtf
                w.writerow([datetime.now().isoformat(timespec="seconds"), backend, device, model,
                            f"{result.audio_seconds:.2f}" if result.audio_seconds else "",
                            f"{result.elapsed:.2f}", f"{rtf:.2f}" if rtf else "",
                            len(text), len(self.vocab.terms())])
        except Exception:
            pass

    # ==== BENCHMARK MODE (temporary, remove after testing) ===================
    def bench_record_start(self) -> None:
        self.bench_recorder.start()

    def bench_record_stop(self) -> dict:
        path = self.bench_recorder.stop_to_wav(config_dir() / "bench-tmp")
        if path is None:
            return {"ok": False, "message": "Trop court (< 0.25s)"}
        try:
            if BENCH_CLIP_PATH.exists():
                BENCH_CLIP_PATH.unlink()
            path.replace(BENCH_CLIP_PATH)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "path": str(BENCH_CLIP_PATH)}

    def run_benchmark(self) -> None:
        if self._bench_running:
            return
        if not BENCH_CLIP_PATH.exists():
            msg = "Enregistre un extrait test d'abord."
            self._js(self.window, f"window.plumeBench && plumeBench.setStatus({json.dumps(msg)})")
            return
        self._bench_running = True
        threading.Thread(target=self._run_benchmark_matrix, daemon=True).start()

    def _bench_emit_row(self, backend, device, model, compute, result=None, error=None) -> dict:
        row = {"backend": backend, "device": device, "model": model, "compute": compute}
        if error is not None:
            row.update({"seconds": "", "rtf": "", "text": f"ERREUR: {error}"})
        else:
            rtf = result.rtf
            row.update({
                "seconds": f"{result.elapsed:.2f}",
                "rtf": f"{rtf:.2f}" if rtf is not None else "",
                "text": result.text,
            })
        self._js(self.window, f"window.plumeBench && plumeBench.addRow({json.dumps(row)})")
        return row

    def _bench_log(self, message: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')} — {message}"
        self._js(self.window, f"window.plumeBench && plumeBench.log({json.dumps(line)})")

    def _run_benchmark_matrix(self) -> None:
        # Everything is wrapped so a crash anywhere (e.g. a bad model path)
        # always resets _bench_running and is reported in the log, instead of
        # dying silently in the background thread and leaving the UI stuck
        # with no feedback and the Lancer button permanently disabled.
        try:
            self._run_benchmark_matrix_inner()
        except Exception as exc:  # noqa: BLE001
            self._bench_log(f"Le benchmark s'est arrêté sur une erreur inattendue : {exc}")
            self._js(self.window, "window.plumeBench && plumeBench.setDone('')")
        finally:
            self._bench_running = False

    def _run_benchmark_matrix_inner(self) -> None:
        rows = []
        language = self.config.get("language")
        language = None if str(language).lower() == "auto" else language

        combos = [
            ("faster-whisper", "cpu", model, compute)
            for model in BENCH_FW_MODELS
            for compute in BENCH_FW_COMPUTE_TYPES
        ]
        ov_models = discover_openvino_models()
        combos += [
            ("openvino", device, model, "int8")
            for model in ov_models
            for device in BENCH_OV_DEVICES
        ]
        if not ov_models:
            note = "Aucun modèle OpenVINO trouvé sous models/openvino/ — seul faster-whisper est testé."
            self._js(self.window, f"window.plumeBench && plumeBench.note({json.dumps(note)})")

        total = len(combos)
        self._bench_log(f"Démarrage : {total} combinaisons à tester sur {BENCH_CLIP_PATH.name}.")
        for i, (backend, device, model, compute) in enumerate(combos, 1):
            label = f"{backend}/{device}/{model}/{compute}"
            self._js(self.window, f"window.plumeBench && plumeBench.setStatus({json.dumps(f'({i}/{total}) {label}')})")
            self._bench_log(
                f"({i}/{total}) {label} — chargement du modèle… "
                "(un modèle jamais utilisé peut télécharger plusieurs centaines de Mo, ça peut prendre du temps)"
            )
            try:
                started_load = time.perf_counter()
                engine = create_backend(backend, model, device, compute, language)
                engine.load()
                load_s = time.perf_counter() - started_load
                self._bench_log(f"({i}/{total}) {label} — modèle chargé en {load_s:.1f}s, transcription…")
                result = engine.transcribe(BENCH_CLIP_PATH)
                row = self._bench_emit_row(backend, device, model, compute, result=result)
                rtf_txt = f", rtf={result.rtf:.2f}" if result.rtf is not None else ""
                self._bench_log(f"({i}/{total}) {label} — OK en {result.elapsed:.2f}s{rtf_txt}")
            except Exception as exc:  # noqa: BLE001
                row = self._bench_emit_row(backend, device, model, compute, error=str(exc))
                self._bench_log(f"({i}/{total}) {label} — ERREUR : {exc}")
            rows.append(row)

        out_path = None
        try:
            out_path = config_dir() / "benchmark-inapp.csv"
            with out_path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=["backend", "device", "model", "compute", "seconds", "rtf", "text"])
                w.writeheader()
                w.writerows(rows)
        except Exception as exc:  # noqa: BLE001
            self._bench_log(f"Impossible d'écrire le CSV : {exc}")
            out_path = None

        self._bench_log("Benchmark terminé.")
        self._js(self.window, f"window.plumeBench && plumeBench.setDone({json.dumps(str(out_path) if out_path else '')})")
    # ==== /BENCHMARK MODE ======================================================

    # ---- hotkey -------------------------------------------------------------
    def _install_hotkey(self) -> None:
        try:
            from pynput import keyboard
        except Exception:
            return
        if self.hotkeys is not None:
            try:
                self.hotkeys.stop()
                self.hotkeys.join(timeout=0.5)
            except Exception:
                pass
            self.hotkeys = None
            self._hotkey = None
        combo = self.config.get("hotkey") or "<ctrl>+<space>"
        try:
            # GlobalHotKeys re-registers the real Windows hook each time the
            # shortcut changes. It is more reliable than keeping a manual
            # press/release listener alive across shortcut edits.
            self.hotkeys = keyboard.GlobalHotKeys({
                combo: lambda: threading.Thread(target=self.toggle, daemon=True).start()
            })
            self.hotkeys.start()
            self._set_status("Raccourci enregistré", "Prêt")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Raccourci invalide : {exc}", "")

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
    def check_for_update(self, notify: bool = True) -> dict:
        try:
            info = latest_release_info()
            self._update_info = info if info.get("available") else None
        except Exception as exc:  # noqa: BLE001
            message = "Release GitHub inaccessible. Le dépôt Plume est probablement privé."
            if "404" not in str(exc):
                message = f"Recherche de mise à jour impossible : {exc}"
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
            self._set_update_ui({**info, "installing": True, "message": "Lancement de l'installeur…"})
            subprocess.Popen([str(dest), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"])
            time.sleep(0.5)
            self.quit()
        except Exception as exc:  # noqa: BLE001
            self._set_update_ui({**info, "installing": False, "message": f"Mise à jour impossible : {exc}"})

    # ---- lifecycle ----------------------------------------------------------
    def _on_started(self) -> None:
        self._start_tray()
        self._install_hotkey()
        set_autostart(bool(self.config.get("autostart")))
        threading.Thread(target=self._preload, daemon=True).start()
        threading.Thread(target=self.check_for_update, daemon=True).start()

    def quit(self) -> None:
        try:
            if self.hotkeys:
                self.hotkeys.stop()
        except Exception:
            pass
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        for win in (self.bubble, self.window):
            try:
                if win is not None:
                    win.destroy()
            except Exception:
                pass

    def run(self) -> None:
        api = Api(self)
        self.window = _create_window(
            "Plume", ui_file("index.html"), js_api=api,
            width=420, height=700, resizable=True, frameless=False,
            easy_drag=False, min_size=(400, 620),
        )
        self.bubble = _create_window(
            "PlumeBubble", ui_file("bubble.html"),
            width=252, height=64, resizable=False, frameless=True,
            on_top=True, transparent=True, background_color="#111318", hidden=True, focus=False,
        )
        webview.start(self._on_started, debug=False)


def _create_window(title, url, **kwargs):
    """create_window that tolerates pywebview versions lacking some kwargs."""
    try:
        return webview.create_window(title, url, **kwargs)
    except TypeError:
        for opt in ("focus", "min_size", "easy_drag", "transparent", "background_color"):
            kwargs.pop(opt, None)
        return webview.create_window(title, url, **kwargs)


class Api:
    """Methods exposed to the web UI as window.pywebview.api.*"""

    def __init__(self, app: PlumeApp) -> None:
        self.app = app

    def get_state(self):
        c = self.app.config
        backend, device = c.get("backend"), c.get("device")
        profile = next((k for k, v in PROFILES.items() if v == (backend, device)), "fw-cpu")
        return {
            "words": self.app.vocab.to_list(),
            "history": c.get("history", []),
            "app_version": APP_VERSION,
            "config": {
                "language": c.get("language"), "model": c.get("model"),
                "profile": profile, "cleanup": c.get("cleanup"),
                "compute": c.get("compute"), "bubble_position": c.get("bubble_position"),
                "hotkey_display": c.get("hotkey_display"),
                "autopaste": c.get("autopaste"), "autostart": c.get("autostart"),
            },
        }

    def toggle(self):
        self.app.toggle()

    def add_word(self, heard, correct):
        self.app.vocab.add(heard, correct)
        self.app.config.set("vocabulary", self.app.vocab.to_list())

    def remove_word(self, index):
        self.app.vocab.remove(int(index))
        self.app.config.set("vocabulary", self.app.vocab.to_list())

    def paste_history(self, index):
        history = self.app.config.get("history", [])
        try:
            text = history[int(index)]["text"]
        except Exception:
            return
        paste_text(text)
        self.app._set_status("Historique recollé", "Prêt")

    def copy_history(self, index):
        history = self.app.config.get("history", [])
        try:
            text = history[int(index)]["text"]
        except Exception:
            return
        copy_text(text)
        self.app._set_status("Historique copié", "Prêt")

    def set_hotkey(self, display):
        self.app.config.data["hotkey_display"] = display
        self.app.config.set("hotkey", hotkey_to_pynput(display))
        self.app._install_hotkey()

    def set_setting(self, key, value):
        if key == "profile":
            backend, device = PROFILES.get(value, PROFILES["fw-cpu"])
            self.app.config.data["backend"] = backend
            self.app.config.data["device"] = device
            current_model = str(self.app.config.get("model") or "")
            if backend == "openvino" and current_model in FAST_WHISPER_MODEL_NAMES:
                self.app.config.data["model"] = DEFAULT_OPENVINO_MODEL
            elif backend == "faster-whisper" and current_model.startswith("models\\openvino\\"):
                self.app.config.data["model"] = "small"
            self.app.config.save()
        else:
            self.app.config.set(key, value)
        if key in ("model", "profile", "compute", "language"):
            threading.Thread(target=self.app._preload, daemon=True).start()
        if key == "autostart":
            set_autostart(bool(value))

    def minimize(self):
        try:
            self.app.window.minimize()
        except Exception:
            try:
                self.app.window.hide()
            except Exception:
                pass

    def hide_window(self):
        try:
            self.app.window.hide()
        except Exception:
            try:
                self.app.window.minimize()
            except Exception:
                pass

    def quit(self):
        self.app.quit()

    def check_update(self):
        return self.app.check_for_update(notify=True)

    def install_update(self):
        threading.Thread(target=self.app._download_and_launch_update, daemon=True).start()
        return {"started": True}

    # ==== BENCHMARK MODE (temporary, remove after testing) ===================
    def bench_record_start(self):
        self.app.bench_record_start()

    def bench_record_stop(self):
        return self.app.bench_record_stop()

    def run_benchmark(self):
        self.app.run_benchmark()
    # ==== /BENCHMARK MODE ======================================================


def main() -> int:
    if sys.platform != "win32":
        print("Plume is Windows-first; the web UI can still open elsewhere for checks.")
    PlumeApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
