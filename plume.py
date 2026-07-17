"""Plume — local voice dictation for Windows, web-glass UI.

Native core (audio, engine, global hotkey, paste, tray) in Python; the UI is an
embedded web view (pywebview). This is a taskbar app with a compact native
window, tray icon and a floating listening bubble.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import webview

from sttlocal import DictationEngine, Recorder, clean_transcript, copy_text, paste_text
from config import Config, config_dir, hotkey_to_pynput
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
            self._hotkey = keyboard.HotKey(keyboard.HotKey.parse(combo), self.toggle)

            def for_canonical(fn):
                return lambda key: fn(self.hotkeys.canonical(key))

            self.hotkeys = keyboard.Listener(
                on_press=for_canonical(self._hotkey.press),
                on_release=for_canonical(self._hotkey.release),
            )
            self.hotkeys.start()
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

    # ---- lifecycle ----------------------------------------------------------
    def _on_started(self) -> None:
        self._start_tray()
        self._install_hotkey()
        set_autostart(bool(self.config.get("autostart")))
        threading.Thread(target=self._preload, daemon=True).start()

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
            width=420, height=660, resizable=True, frameless=False,
            easy_drag=False, min_size=(400, 600),
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
            pass

    def hide_window(self):
        try:
            self.app.window.hide()
        except Exception:
            pass

    def quit(self):
        self.app.quit()


def main() -> int:
    if sys.platform != "win32":
        print("Plume is Windows-first; the web UI can still open elsewhere for checks.")
    PlumeApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
