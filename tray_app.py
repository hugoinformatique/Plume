from __future__ import annotations

import argparse
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path

from sttlocal import DictationEngine, Recorder, clean_transcript, paste_text
from ui_theme import (
    ACCENT, BORDER, BRAND, CARD, DANGER, MUTED, SURFACE, TEXT_DARK, FONT_UI,
)


tk = None
ttk = None
Image = None
ImageDraw = None
ImageTk = None
keyboard = None
ListeningBubble = None

MODELS = ["base", "small", "medium", "turbo"]
BACKENDS = ["faster-whisper", "openvino"]
COMPUTE_TYPES = ["int8", "int8_float16", "float16", "float32"]
CLEANUP_MODES = ["off", "light", "strong"]
BUBBLE_POSITIONS = ["bottom", "top"]
APP_NAME = "Plume"

# Named engine presets surfaced in the tray right-click menu.
# (label, backend, device)
PROFILES = [
    ("Rapide - faster-whisper (CPU)", "faster-whisper", "cpu"),
    ("NPU - OpenVINO (AI Boost)", "openvino", "NPU"),
    ("iGPU - OpenVINO (Arc)", "openvino", "GPU"),
    ("OpenVINO (CPU)", "openvino", "CPU"),
]


def load_gui_dependencies() -> None:
    global tk, ttk, Image, ImageDraw, ImageTk, keyboard, ListeningBubble
    try:
        import tkinter as tk_module
        from tkinter import ttk as ttk_module

        from PIL import Image as image_module
        from PIL import ImageDraw as image_draw_module
        from PIL import ImageTk as image_tk_module
        from pynput import keyboard as keyboard_module

        from listening_bubble import ListeningBubble as bubble_cls
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing GUI dependency. On Windows, reinstall Python with the optional Tcl/Tk support, "
            "then run: python -m pip install -r requirements.txt"
        ) from exc

    tk = tk_module
    ttk = ttk_module
    Image = image_module
    ImageDraw = image_draw_module
    ImageTk = image_tk_module
    keyboard = keyboard_module
    ListeningBubble = bubble_cls


class TrayDictationApp:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("580x560")
        self.root.minsize(520, 520)
        self.root.configure(bg=SURFACE)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.events: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self.recorder = Recorder()
        self.engine: DictationEngine | None = None
        self._engine_key_cached: tuple | None = None
        self.engine_lock = threading.Lock()
        self.worker: threading.Thread | None = None
        self.hotkeys: keyboard.GlobalHotKeys | None = None
        self.tray_icon = None
        self.bubble = None
        self.preview_lock = threading.Lock()
        self.recordings_dir = Path(args.recordings_dir)
        self._icon_images: dict = {}

        self.model_var = tk.StringVar(value=args.model)
        self.language_var = tk.StringVar(value=args.language)
        self.backend_var = tk.StringVar(value=args.backend)
        self.device_var = tk.StringVar(value=args.device)
        self.compute_var = tk.StringVar(value=args.compute_type)
        self.cleanup_var = tk.StringVar(value=args.cleanup)
        self.live_preview_var = tk.BooleanVar(value=args.live_preview)
        self.position_var = tk.StringVar(value=args.bubble_position)
        self.status_var = tk.StringVar(value="Demarrage...")

        # Plain mirrors of the current engine choice, read by the tray menu
        # (avoids touching Tk variables from the pystray thread).
        self._menu_model = args.model
        self._menu_backend = args.backend
        self._menu_device = args.device

        self._set_window_icon()
        self._build_ui()
        self.bubble = ListeningBubble(self.root, position=self.position_var.get())
        self._install_hotkeys()
        self._start_tray()
        self.root.after(100, self._poll_events)
        # Warm the engine up front so the first F9 is fast.
        self._schedule_preload()

    # --- icon / theme --------------------------------------------------------
    def _icon_photo(self, size: int):
        from ui_theme import make_icon_image

        assets_png = Path(__file__).resolve().parent / "assets" / "plume.png"
        try:
            if assets_png.exists():
                src = Image.open(assets_png).convert("RGBA").resize((size, size), Image.LANCZOS)
            else:
                src = make_icon_image(size)
            photo = ImageTk.PhotoImage(src)
            self._icon_images[size] = photo  # keep a reference
            return photo
        except Exception:
            return None

    def _set_window_icon(self) -> None:
        try:
            photo = self._icon_photo(64)
            if photo is not None:
                self.root.iconphoto(True, photo)
        except Exception:
            pass

    # --- UI ------------------------------------------------------------------
    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=SURFACE)
        style.configure("Card.TLabelframe", background=CARD, bordercolor=BORDER)
        style.configure("Card.TLabelframe.Label", background=SURFACE, foreground=MUTED, font=(FONT_UI, 10, "bold"))
        style.configure("TLabel", background=CARD, foreground=TEXT_DARK, font=(FONT_UI, 10))
        style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED, font=(FONT_UI, 10))
        style.configure("TCombobox", font=(FONT_UI, 10))
        style.configure("TCheckbutton", background=CARD, foreground=TEXT_DARK, font=(FONT_UI, 10))

        # Header ---------------------------------------------------------------
        header = tk.Frame(self.root, bg=SURFACE)
        header.pack(fill="x", padx=20, pady=(18, 8))
        logo = self._icon_photo(44)
        if logo is not None:
            tk.Label(header, image=logo, bg=SURFACE).pack(side="left", padx=(0, 12))
        title_box = tk.Frame(header, bg=SURFACE)
        title_box.pack(side="left", anchor="w")
        tk.Label(title_box, text=APP_NAME, bg=SURFACE, fg=TEXT_DARK, font=(FONT_UI, 20, "bold")).pack(anchor="w")
        tk.Label(title_box, text="Dictee locale - rien ne quitte votre PC",
                 bg=SURFACE, fg=MUTED, font=(FONT_UI, 10)).pack(anchor="w")

        # Record button --------------------------------------------------------
        record_row = tk.Frame(self.root, bg=SURFACE)
        record_row.pack(fill="x", padx=20, pady=(6, 4))
        self.toggle_button = tk.Button(
            record_row, text="Demarrer la dictee  (F9)", command=self.toggle_recording,
            bg=ACCENT, fg="#08251E", activebackground=ACCENT, activeforeground="#08251E",
            font=(FONT_UI, 12, "bold"), relief="flat", bd=0, padx=16, pady=12, cursor="hand2",
        )
        self.toggle_button.pack(fill="x")
        self.status_dot = tk.Label(self.root, textvariable=self.status_var, bg=SURFACE, fg=MUTED,
                                   font=(FONT_UI, 10), anchor="w")
        self.status_dot.pack(fill="x", padx=22, pady=(2, 8))

        # Settings -------------------------------------------------------------
        settings = ttk.LabelFrame(self.root, text=" Moteur ", style="Card.TLabelframe")
        settings.pack(fill="x", padx=20, pady=6)
        pad = {"padx": 10, "pady": 6}

        ttk.Label(settings, text="Modele").grid(row=0, column=0, sticky="w", **pad)
        ttk.Combobox(settings, textvariable=self.model_var, values=MODELS, width=16).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(settings, text="Langue").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(settings, textvariable=self.language_var, width=8).grid(row=0, column=3, sticky="w", **pad)

        ttk.Label(settings, text="Backend").grid(row=1, column=0, sticky="w", **pad)
        ttk.Combobox(settings, textvariable=self.backend_var, values=BACKENDS, width=16).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(settings, text="Device").grid(row=1, column=2, sticky="w", **pad)
        ttk.Entry(settings, textvariable=self.device_var, width=8).grid(row=1, column=3, sticky="w", **pad)

        ttk.Label(settings, text="Compute").grid(row=2, column=0, sticky="w", **pad)
        ttk.Combobox(settings, textvariable=self.compute_var, values=COMPUTE_TYPES, width=16).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(settings, text="Nettoyage").grid(row=2, column=2, sticky="w", **pad)
        ttk.Combobox(settings, textvariable=self.cleanup_var, values=CLEANUP_MODES, width=8).grid(row=2, column=3, sticky="w", **pad)

        ttk.Label(settings, text="Bulle").grid(row=3, column=0, sticky="w", **pad)
        ttk.Combobox(settings, textvariable=self.position_var, values=BUBBLE_POSITIONS, width=16).grid(row=3, column=1, sticky="w", **pad)
        ttk.Checkbutton(settings, text="Apercu pendant l'enregistrement", variable=self.live_preview_var).grid(
            row=3, column=2, columnspan=2, sticky="w", **pad
        )

        apply_btn = tk.Button(settings, text="Appliquer / recharger le moteur", command=self._apply_settings,
                              bg=BRAND, fg="#FFFFFF", activebackground=BRAND, activeforeground="#FFFFFF",
                              font=(FONT_UI, 10, "bold"), relief="flat", bd=0, padx=12, pady=8, cursor="hand2")
        apply_btn.grid(row=4, column=0, columnspan=4, sticky="we", **pad)

        # Output ---------------------------------------------------------------
        out = ttk.LabelFrame(self.root, text=" Derniere transcription ", style="Card.TLabelframe")
        out.pack(fill="both", expand=True, padx=20, pady=(6, 8))
        self.output = tk.Text(out, height=8, wrap="word", relief="flat", bd=0,
                              bg=CARD, fg=TEXT_DARK, font=(FONT_UI, 11), padx=10, pady=8)
        self.output.pack(fill="both", expand=True, padx=8, pady=8)
        self.output.insert("end", "F9 pour demarrer/arreter. Le texte est colle dans l'application active.\n")
        self.output.configure(state="disabled")

        # Footer ---------------------------------------------------------------
        footer = tk.Frame(self.root, bg=SURFACE)
        footer.pack(fill="x", padx=20, pady=(0, 16))
        tk.Button(footer, text="Reduire dans la barre", command=self.hide_window,
                  bg=CARD, fg=TEXT_DARK, relief="flat", bd=1, padx=12, pady=6, cursor="hand2").pack(side="left")
        tk.Button(footer, text="Quitter", command=self.quit,
                  bg=CARD, fg=DANGER, relief="flat", bd=1, padx=12, pady=6, cursor="hand2").pack(side="right")

    # --- engine (kept warm) --------------------------------------------------
    def _engine_key(self) -> tuple:
        lang = self.language_var.get().strip()
        return (
            self.backend_var.get().strip(),
            self.model_var.get().strip(),
            self.device_var.get().strip(),
            self.compute_var.get().strip(),
            None if lang.lower() == "auto" else lang,
        )

    def _get_engine(self, key: tuple) -> DictationEngine:
        """Build the engine once and reuse it; rebuild only if the key changed.

        Safe to call from a worker thread: `key` carries plain values, no Tk
        access happens here.
        """
        with self.engine_lock:
            if self.engine is None or key != self._engine_key_cached:
                backend, model, device, compute, language = key
                engine = DictationEngine(
                    model_name=model, device=device, compute_type=compute,
                    language=language, backend=backend,
                )
                engine.load()
                self.engine = engine
                self._engine_key_cached = key
            return self.engine

    def _schedule_preload(self) -> None:
        key = self._engine_key()
        self.status_var.set("Chargement du modele...")

        def worker() -> None:
            try:
                self._get_engine(key)
                self.events.put(("status_ready", None))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_settings(self) -> None:
        self._menu_model = self.model_var.get().strip()
        self._menu_backend = self.backend_var.get().strip()
        self._menu_device = self.device_var.get().strip()
        if self.position_var.get() in BUBBLE_POSITIONS and self.bubble is not None:
            self.bubble.position = self.position_var.get()
        self._refresh_tray_menu()
        self._schedule_preload()

    # --- hotkeys / tray ------------------------------------------------------
    def _install_hotkeys(self) -> None:
        self.hotkeys = keyboard.GlobalHotKeys({"<f9>": lambda: self.events.put(("toggle", None))})
        self.hotkeys.start()

    def _tray_image(self):
        from ui_theme import make_icon_image

        assets_png = Path(__file__).resolve().parent / "assets" / "plume.png"
        try:
            if assets_png.exists():
                return Image.open(assets_png).convert("RGBA")
        except Exception:
            pass
        return make_icon_image(64)

    def _build_menu(self):
        import pystray

        def ev(name, payload=None):
            return lambda icon=None, item=None: self.events.put((name, payload))

        def model_item(m):
            return pystray.MenuItem(
                m, ev("set_model", m),
                checked=lambda item, mm=m: self._menu_model == mm, radio=True,
            )

        def profile_item(p):
            label, be, dev = p
            return pystray.MenuItem(
                label, ev("set_profile", p),
                checked=lambda item, pp=p: (self._menu_backend, self._menu_device) == (pp[1], pp[2]),
                radio=True,
            )

        model_menu = pystray.Menu(*[model_item(m) for m in MODELS])
        profile_menu = pystray.Menu(*[profile_item(p) for p in PROFILES])

        return pystray.Menu(
            pystray.MenuItem(f"{APP_NAME} - dictee locale", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Demarrer / Arreter (F9)", ev("toggle")),
            pystray.MenuItem("Afficher la fenetre", ev("show"), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Modele", model_menu),
            pystray.MenuItem("Moteur", profile_menu),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", ev("quit")),
        )

    def _start_tray(self) -> None:
        try:
            import pystray

            self.tray_icon = pystray.Icon(APP_NAME, self._tray_image(), APP_NAME, self._build_menu())
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as exc:  # noqa: BLE001
            self.log(f"Tray indisponible: {exc}")

    def _refresh_tray_menu(self) -> None:
        try:
            if self.tray_icon is not None:
                self.tray_icon.update_menu()
        except Exception:
            pass

    # --- window --------------------------------------------------------------
    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(200, lambda: self.root.attributes("-topmost", False))

    def hide_window(self) -> None:
        self.root.withdraw()

    # --- recording -----------------------------------------------------------
    def toggle_recording(self) -> None:
        if self.worker and self.worker.is_alive():
            self.log("Transcription en cours, patiente.")
            return
        if self.recorder.is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        self.replace_output("")
        self.recorder.start()
        self.status_var.set("Enregistrement... F9 pour arreter")
        self.toggle_button.configure(text="Arreter  (F9)", bg=DANGER, activebackground=DANGER, fg="#FFFFFF")
        if self.bubble is not None:
            self.bubble.position = self.position_var.get()
            self.bubble.show("listening", "A l'ecoute...")
        if self.live_preview_var.get():
            threading.Thread(target=self._preview_loop, daemon=True).start()

    def _stop_recording(self) -> None:
        path = self.recorder.stop_to_wav(self.recordings_dir)
        self.toggle_button.configure(text="Demarrer la dictee  (F9)", bg=ACCENT,
                                     activebackground=ACCENT, fg="#08251E")
        if path is None:
            self.status_var.set("Enregistrement trop court")
            if self.bubble is not None:
                self.bubble.hide()
            return
        self.status_var.set("Transcription locale...")
        if self.bubble is not None:
            self.bubble.set_state("transcribing", "Transcription...")
        key = self._engine_key()
        cleanup = self.cleanup_var.get()
        self.worker = threading.Thread(
            target=self._transcribe_and_paste, args=(path, key, cleanup), daemon=True
        )
        self.worker.start()

    def _preview_loop(self) -> None:
        last_preview_at = 0.0
        while self.recorder.is_recording:
            if time.perf_counter() - last_preview_at < 3.0:
                time.sleep(0.2)
                continue
            last_preview_at = time.perf_counter()
            path = self.recorder.snapshot_to_wav(Path(tempfile.gettempdir()) / "plume-preview")
            if path is not None:
                self.events.put(("preview", path))

    def _transcribe_and_paste(self, path: Path, key: tuple, cleanup: str) -> None:
        try:
            engine = self._get_engine(key)
            raw_text, elapsed, language, probability = engine.transcribe(path)
            text = raw_text if cleanup == "off" else clean_transcript(raw_text, cleanup)
            self.events.put(("final_text", (text, raw_text, elapsed, language, probability)))
            if text:
                paste_text(text)
                self.events.put(("status", "Texte colle dans l'application active."))
            else:
                self.events.put(("status", "Aucun texte detecte."))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", exc))

    def _transcribe_preview(self, path: Path, key: tuple, cleanup: str) -> None:
        if not self.preview_lock.acquire(blocking=False):
            return
        try:
            if self.worker and self.worker.is_alive():
                return
            engine = self._get_engine(key)
            raw_text, _elapsed, _language, _prob = engine.transcribe(path)
            if raw_text:
                text = raw_text if cleanup == "off" else clean_transcript(raw_text, cleanup)
                self.events.put(("preview_text", text))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("preview_error", exc))
        finally:
            self.preview_lock.release()

    # --- event loop ----------------------------------------------------------
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
                return
            elif event == "status_ready":
                self.status_var.set("Pret - F9 pour dicter")
            elif event == "set_model":
                self.model_var.set(str(payload))
                self._menu_model = str(payload)
                self._refresh_tray_menu()
                self._schedule_preload()
            elif event == "set_profile":
                label, be, dev = payload
                self.backend_var.set(be)
                self.device_var.set(dev)
                self._menu_backend, self._menu_device = be, dev
                self._refresh_tray_menu()
                self._schedule_preload()
            elif event == "preview":
                key = self._engine_key()
                cleanup = self.cleanup_var.get()
                threading.Thread(target=self._transcribe_preview, args=(payload, key, cleanup), daemon=True).start()
            elif event == "preview_text":
                self.status_var.set("Apercu local...")
                self.replace_output(str(payload))
            elif event == "final_text":
                text, raw_text, elapsed, language, probability = payload
                self.status_var.set(f"Termine en {elapsed:.2f}s - {language} ({probability:.0%})")
                self.replace_output(text or raw_text or "")
                if self.bubble is not None:
                    if text:
                        self.bubble.flash_done("Colle")
                    else:
                        self.bubble.hide()
            elif event == "status":
                self.status_var.set(str(payload))
                self.log(str(payload))
            elif event == "error":
                self.status_var.set(f"Erreur: {payload}")
                self.log(f"Erreur: {payload}")
                if self.bubble is not None:
                    self.bubble.hide()
            elif event == "preview_error":
                self.log(f"Apercu indisponible: {payload}")

        self.root.after(100, self._poll_events)

    # --- output helpers ------------------------------------------------------
    def replace_output(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        if text:
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
        if self.bubble is not None:
            self.bubble.hide()
        if self.hotkeys:
            self.hotkeys.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Windows tray dictation app")
    parser.add_argument("--model", default="small", help="Model name, or a converted model dir for openvino")
    parser.add_argument("--language", default="fr")
    parser.add_argument("--backend", default="faster-whisper", choices=BACKENDS)
    parser.add_argument("--device", default="cpu", help="faster-whisper: cpu/cuda. openvino: CPU/GPU/NPU.")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--cleanup", default="light", choices=CLEANUP_MODES)
    parser.add_argument("--bubble-position", default="bottom", choices=BUBBLE_POSITIONS)
    parser.add_argument("--live-preview", action="store_true")
    parser.add_argument("--recordings-dir", default="recordings")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("Warning: this app is Windows-first. It can open elsewhere for syntax/UI checks.")

    load_gui_dependencies()
    return TrayDictationApp(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
