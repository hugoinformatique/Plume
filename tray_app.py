from __future__ import annotations

import argparse
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path

from sttlocal import DictationEngine, Recorder, clean_transcript, paste_text


tk = None
ttk = None
Image = None
ImageDraw = None
keyboard = None

MODELS = ["base", "small", "medium", "turbo"]
COMPUTE_TYPES = ["int8", "int8_float16", "float16", "float32"]
CLEANUP_MODES = ["off", "light", "strong"]
APP_NAME = "ScribeLocal"


def load_gui_dependencies() -> None:
    global tk, ttk, Image, ImageDraw, keyboard
    try:
        import tkinter as tk_module
        from tkinter import ttk as ttk_module

        from PIL import Image as image_module
        from PIL import ImageDraw as image_draw_module
        from pynput import keyboard as keyboard_module
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing GUI dependency. On Windows, reinstall Python with the optional Tcl/Tk support, "
            "then run: python -m pip install -r requirements.txt"
        ) from exc

    tk = tk_module
    ttk = ttk_module
    Image = image_module
    ImageDraw = image_draw_module
    keyboard = keyboard_module


class TrayDictationApp:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("560x430")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.events: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self.recorder = Recorder()
        self.engine: DictationEngine | None = None
        self.worker: threading.Thread | None = None
        self.hotkeys: keyboard.GlobalHotKeys | None = None
        self.tray_icon = None
        self.stop_requested = False
        self.preview_lock = threading.Lock()
        self.recordings_dir = Path(args.recordings_dir)

        self.model_var = tk.StringVar(value=args.model)
        self.language_var = tk.StringVar(value=args.language)
        self.device_var = tk.StringVar(value=args.device)
        self.compute_var = tk.StringVar(value=args.compute_type)
        self.cleanup_var = tk.StringVar(value=args.cleanup)
        self.live_preview_var = tk.BooleanVar(value=args.live_preview)
        self.status_var = tk.StringVar(value="Pret - F9 pour enregistrer")
        self.hotkey_var = tk.StringVar(value="F9")

        self._build_ui()
        self._install_hotkeys()
        self._start_tray()
        self.root.after(100, self._poll_events)

    def _build_ui(self) -> None:
        padding = {"padx": 12, "pady": 6}

        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=14, pady=(14, 8))
        ttk.Label(header, text=APP_NAME, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(header, text="Dictee locale Windows - aucun envoi cloud").pack(anchor="w")

        settings = ttk.LabelFrame(self.root, text="Moteur")
        settings.pack(fill="x", padx=14, pady=8)

        ttk.Label(settings, text="Modele").grid(row=0, column=0, sticky="w", **padding)
        ttk.Combobox(settings, textvariable=self.model_var, values=MODELS, width=15).grid(row=0, column=1, sticky="w", **padding)
        ttk.Label(settings, text="Langue").grid(row=0, column=2, sticky="w", **padding)
        ttk.Entry(settings, textvariable=self.language_var, width=8).grid(row=0, column=3, sticky="w", **padding)

        ttk.Label(settings, text="Device").grid(row=1, column=0, sticky="w", **padding)
        ttk.Entry(settings, textvariable=self.device_var, width=17).grid(row=1, column=1, sticky="w", **padding)
        ttk.Label(settings, text="Compute").grid(row=1, column=2, sticky="w", **padding)
        ttk.Combobox(settings, textvariable=self.compute_var, values=COMPUTE_TYPES, width=13).grid(row=1, column=3, sticky="w", **padding)

        ttk.Label(settings, text="Nettoyage").grid(row=2, column=0, sticky="w", **padding)
        ttk.Combobox(settings, textvariable=self.cleanup_var, values=CLEANUP_MODES, width=15).grid(row=2, column=1, sticky="w", **padding)
        ttk.Checkbutton(settings, text="Preview pendant l'enregistrement", variable=self.live_preview_var).grid(
            row=2, column=2, columnspan=2, sticky="w", **padding
        )

        controls = ttk.Frame(self.root)
        controls.pack(fill="x", padx=14, pady=6)
        self.toggle_button = ttk.Button(controls, text="Demarrer F9", command=self.toggle_recording)
        self.toggle_button.pack(side="left")
        ttk.Button(controls, text="Cacher", command=self.hide_window).pack(side="left", padx=8)
        ttk.Button(controls, text="Quitter", command=self.quit).pack(side="right")

        status = ttk.LabelFrame(self.root, text="Etat")
        status.pack(fill="both", expand=True, padx=14, pady=(8, 14))
        ttk.Label(status, textvariable=self.status_var).pack(anchor="w", padx=10, pady=(8, 2))
        self.output = tk.Text(status, height=11, wrap="word")
        self.output.pack(fill="both", expand=True, padx=10, pady=8)
        self.output.insert("end", "F9 start/stop. Le texte final est colle dans l'application active.\n")
        self.output.configure(state="disabled")

    def _install_hotkeys(self) -> None:
        self.hotkeys = keyboard.GlobalHotKeys({"<f9>": lambda: self.events.put(("toggle", None))})
        self.hotkeys.start()

    def _start_tray(self) -> None:
        try:
            import pystray

            image = Image.new("RGB", (64, 64), "#1f6feb")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((10, 10, 54, 54), radius=10, fill="#ffffff")
            draw.text((22, 21), "ST", fill="#1f6feb")
            menu = pystray.Menu(
                pystray.MenuItem("Afficher", lambda: self.events.put(("show", None))),
                pystray.MenuItem("Start/Stop F9", lambda: self.events.put(("toggle", None))),
                pystray.MenuItem("Quitter", lambda: self.events.put(("quit", None))),
            )
            self.tray_icon = pystray.Icon(APP_NAME, image, APP_NAME, menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as exc:
            self.log(f"Tray indisponible: {exc}")

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()

    def hide_window(self) -> None:
        self.root.withdraw()

    def toggle_recording(self) -> None:
        if self.worker and self.worker.is_alive():
            self.log("Transcription deja en cours, patiente.")
            return

        if self.recorder.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self.recorder.start()
        self.status_var.set("Enregistrement... F9 pour arreter")
        self.toggle_button.configure(text="Arreter F9")
        self.log("Enregistrement demarre.")
        if self.live_preview_var.get():
            threading.Thread(target=self._preview_loop, daemon=True).start()

    def _stop_recording(self) -> None:
        path = self.recorder.stop_to_wav(self.recordings_dir)
        self.toggle_button.configure(text="Demarrer F9")
        if path is None:
            self.status_var.set("Enregistrement trop court")
            return
        self.status_var.set("Transcription locale en cours...")
        self.worker = threading.Thread(target=self._transcribe_and_paste, args=(path,), daemon=True)
        self.worker.start()

    def _preview_loop(self) -> None:
        last_preview_at = 0.0
        while self.recorder.is_recording:
            if time.perf_counter() - last_preview_at < 3.0:
                time.sleep(0.2)
                continue
            last_preview_at = time.perf_counter()
            path = self.recorder.snapshot_to_wav(Path(tempfile.gettempdir()) / "sttlocal-preview")
            if path is not None:
                self.events.put(("preview", path))

    def _engine_from_ui(self) -> DictationEngine:
        language = self.language_var.get().strip()
        return DictationEngine(
            model_name=self.model_var.get().strip(),
            device=self.device_var.get().strip(),
            compute_type=self.compute_var.get().strip(),
            language=None if language.lower() == "auto" else language,
        )

    def _transcribe_and_paste(self, path: Path) -> None:
        try:
            self.engine = self._engine_from_ui()
            raw_text, elapsed, language, probability = self.engine.transcribe(path)
            mode = self.cleanup_var.get()
            text = raw_text if mode == "off" else clean_transcript(raw_text, mode)
            self.events.put(("final_text", (text, raw_text, elapsed, language, probability)))
            if text:
                paste_text(text)
                self.events.put(("status", "Texte colle dans l'application active."))
            else:
                self.events.put(("status", "Aucun texte detecte."))
        except Exception as exc:
            self.events.put(("error", exc))

    def _transcribe_preview(self, path: Path) -> None:
        if not self.preview_lock.acquire(blocking=False):
            return
        try:
            if self.worker and self.worker.is_alive():
                return
            if self.engine is None:
                self.engine = self._engine_from_ui()
            raw_text, elapsed, language, probability = self.engine.transcribe(path)
            if raw_text:
                cleanup = self.cleanup_var.get()
                text = raw_text if cleanup == "off" else clean_transcript(raw_text, cleanup)
                self.events.put(("preview_text", text))
        except Exception as exc:
            self.events.put(("preview_error", exc))
        finally:
            self.preview_lock.release()

    def _poll_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "toggle":
                self.toggle_recording()
            elif event == "show":
                self.show_window()
            elif event == "quit":
                self.quit()
            elif event == "preview":
                threading.Thread(target=self._transcribe_preview, args=(payload,), daemon=True).start()
            elif event == "preview_text":
                self.status_var.set("Preview local en cours...")
                self.replace_output(str(payload))
            elif event == "final_text":
                text, raw_text, elapsed, language, probability = payload
                self.status_var.set(f"Termine en {elapsed:.2f}s - langue {language} ({probability:.0%})")
                self.replace_output(text or raw_text or "")
            elif event == "status":
                self.status_var.set(str(payload))
                self.log(str(payload))
            elif event == "error":
                self.status_var.set(f"Erreur: {payload}")
                self.log(f"Erreur: {payload}")
            elif event == "preview_error":
                self.log(f"Preview indisponible: {payload}")

        self.root.after(100, self._poll_events)

    def replace_output(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("end", text)
        self.output.configure(state="disabled")

    def log(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", f"{text}\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    def quit(self) -> None:
        if self.recorder.is_recording:
            self.recorder.stop_to_wav(self.recordings_dir)
        if self.hotkeys:
            self.hotkeys.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Windows tray app")
    parser.add_argument("--model", default="small", choices=MODELS)
    parser.add_argument("--language", default="fr")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--cleanup", default="light", choices=CLEANUP_MODES)
    parser.add_argument("--live-preview", action="store_true")
    parser.add_argument("--recordings-dir", default="recordings")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("Warning: this app is Windows-first. It can open elsewhere for syntax/UI checks.")

    load_gui_dependencies()
    return TrayDictationApp(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
