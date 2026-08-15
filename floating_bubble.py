"""Native Tk floating "listening" bubble, self-contained and thread-safe.

Liquid Glass / Water Droplet (Goutte d'eau) aesthetic:
A frameless, always-on-top translucent liquid glass pill with optical depth,
convex specular glares, volumetric refractions, a breathing 3D water-droplet bead,
and voice-reactive fluid wave ripples.

Plume's main thread belongs to ``webview.start()``, so this module owns its
*own* Tk root running in its own daemon thread. Every public method may be
called from any thread (hotkey listener, transcription worker, pywebview
bridge): work is marshalled onto the Tk thread through a queue drained by a
small poller, so no Tk object is ever touched from outside that thread.

It is deliberately defensive. If tkinter is missing, or the root cannot be
created, or any Tk call blows up, the bubble silently becomes a no-op and the
dictation keeps working -- a decoration must never take the app down.
"""

from __future__ import annotations

import math
import queue
import threading

from config import debug_log
from ui_theme import FONT_UI, mix

# --- geometry / look ---------------------------------------------------------
CHROMA = "#010101"       # transparent-color key -> rounded corners on Windows
BUBBLE_W = 276
BUBBLE_H = 68
RADIUS = 30              # organic fluid pebble / water droplet curvature
MARGIN = 40              # distance from the top/bottom edge of the work area

BAR_COUNT = 7            # 7 voice-reactive fluid wave ripples
BAR_W = 5.0              # rounded droplet capsule width
BAR_GAP = 11.5
BAR_MAX = 19.0           # max amplitude (half-height, keeps bars inside the pill)
EASE_UP = 0.38           # responsive liquid crest rise
EASE_DOWN = 0.22         # buoyant, floaty fluid descent

FRAME_MS = 33            # ~30 fps
PUMP_MS = 30             # cross-thread command poll (cheap, not a busy loop)

# --- Liquid Glass / Water Droplet Optics Palette -----------------------------
# Deep obsidian liquid glass with subtle midnight refraction
SHADOW_DEPTH = "#030508"         # soft contact shadow beneath the droplet
GLASS_BASE = "#0C0F17"           # smoked liquid glass body
GLASS_CORE = "#121724"           # inner refracted liquid volume
GLASS_CRESCENT = "#192233"       # top convex meniscus glare polygon
SPECULAR_TOP = "#3B5270"         # soft top curvature highlight arc
SPECULAR_PEAK = "#82A7CF"        # bright light streak along the top rim
SPECULAR_CORE = "#E2F0FD"        # pure brilliance apex highlight
CAUSTIC_BOTTOM = "#172233"       # bottom internal caustic light reflection
MENISCUS_BORDER = "#2A384C"      # luminous glass surface tension rim

# States: Liquid Aqua/Mint (Listening) -> Oceanic Vortex (Transcribing) -> Crystal Flash (Done)
TEXT_LIVE = "#F8FAFC"            # crisp crystalline white label
TEXT_SPIN = "#94A3B8"            # softened translucent label
TEXT_DONE = "#FFFFFF"            # pure white confirmation

# Listening state tokens
AURA_LIVE = "#063328"            # breathing liquid aura
LIVE_CORE = "#00F5B8"            # glowing aqua-mint water droplet bead
LIVE_BAR_CENTER = "#00F5B8"      # center wave peaks
LIVE_BAR_FLANK = "#14B8A6"       # outer wave bars

# Transcribing state tokens
AURA_SPIN = "#111C2E"            # oceanic halo
SPIN_CORE = "#38BDF8"            # sapphire-cyan vortex droplet
SPIN_CORE_ALT = "#818CF8"        # dynamic vortex phase hue
SPIN_BAR_ACTIVE = "#38BDF8"      # traveling wave crest
SPIN_BAR_DIM = "#1E293B"         # dimmed wave baseline

# Done state tokens
AURA_DONE = "#0369A1"            # crystalline flash aura
DONE_CORE = "#FFFFFF"            # diamond droplet
DONE_BAR = "#FFFFFF"             # confirmation wave


def _rr_points(x1: float, y1: float, x2: float, y2: float, r: float) -> list[float]:
    """Corner points for a rounded rectangle drawn as a ``smooth=True`` polygon.

    Duplicating the corner anchors is the classic Tk trick: the spline then
    hugs the corners instead of rounding the whole shape into a blob.
    """
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def _capsule_points(cx: float, cy: float, half_h: float, w: float) -> list[float]:
    """A vertical bar with round caps: a rounded rect of radius = half width."""
    half_w = w / 2.0
    half_h = max(half_h, half_w)
    return _rr_points(cx - half_w, cy - half_h, cx + half_w, cy + half_h, half_w)


def _specular_crescent_points(w: float, h: float, r: float) -> list[float]:
    """Convex top specular highlight polygon mimicking curved water drop glare."""
    x1, y1, x2, y2 = 4.0, 3.0, w - 4.0, h * 0.42
    cr = r * 0.85
    return [
        x1 + cr, y1,
        x2 - cr, y1,
        x2, y1 + cr * 0.4,
        x2 - cr * 0.5, y2,
        w / 2.0, y2 + 1.5,
        x1 + cr * 0.5, y2,
        x1, y1 + cr * 0.4,
    ]


def _work_area(fallback_w: int, fallback_h: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the desktop minus the taskbar, if we can."""
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
            0x0030, 0, ctypes.byref(rect), 0  # SPI_GETWORKAREA
        )
        if ok and rect.right > rect.left and rect.bottom > rect.top:
            return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        pass
    return (0, 0, int(fallback_w), int(fallback_h))


def _virtual_screen(fallback_w: int, fallback_h: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the whole virtual desktop."""
    try:
        import ctypes

        u = ctypes.windll.user32  # type: ignore[attr-defined]
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
        SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
        left, top = u.GetSystemMetrics(SM_XVIRTUALSCREEN), u.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width, height = u.GetSystemMetrics(SM_CXVIRTUALSCREEN), u.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if width > 0 and height > 0:
            return (int(left), int(top), int(left + width), int(top + height))
    except Exception:
        pass
    return (0, 0, int(fallback_w), int(fallback_h))


def _no_activate(win) -> None:
    """Ask Windows never to activate this window (the paste must land elsewhere)."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        hwnd = user32.GetParent(wintypes.HWND(win.winfo_id())) or win.winfo_id()
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080
        get_l = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_l = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get_l.argtypes = [wintypes.HWND, ctypes.c_int]
        get_l.restype = ctypes.c_void_p
        set_l.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        set_l.restype = ctypes.c_void_p
        style = get_l(wintypes.HWND(hwnd), GWL_EXSTYLE) or 0
        set_l(wintypes.HWND(hwnd), GWL_EXSTYLE,
              ctypes.c_void_p(int(style) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW))
    except Exception as exc:  # noqa: BLE001
        debug_log(f"bubble: could not set WS_EX_NOACTIVATE: {type(exc).__name__}: {exc}")


class FloatingBubble:
    """A translucent liquid glass floating pill showing dictation state.

    Public methods are thread-safe and never raise.
    """

    def __init__(self, position: str = "bottom", pos: tuple[int, int] | None = None,
                 on_move=None) -> None:
        self.position = position if position in ("top", "bottom") else "bottom"
        self.pos = tuple(pos) if pos else None
        self.on_move = on_move

        # Cross-thread plumbing.
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._dead = False           # tkinter unavailable / shut down -> no-op
        self._stopping = False
        self._tk_ident: int | None = None

        # Tk-thread-only state.
        self._tk = None
        self._root = None
        self._win = None
        self._canvas = None

        # Graphical elements
        self._dot_halo = None
        self._dot = None
        self._dot_spec = None
        self._label = None
        self._bars: list[tuple[int, float]] = []
        self._bar_vals: list[float] = [BAR_W / 2.0] * BAR_COUNT

        self._state = "hidden"
        self._visible = False
        self._phase = 0.0
        self._anim_id = None
        self._hide_id = None
        self._alpha = 0.96
        self._drag: tuple[int, int] | None = None
        self._drag_moved = False

        # Written from any thread, read from the Tk thread (atomic float store).
        self._level = 0.0

    # --- thread plumbing -----------------------------------------------------
    def _ensure_thread(self) -> bool:
        with self._lock:
            if self._dead:
                return False
            if self._thread is not None:
                return self._ready.is_set() and not self._dead
            try:
                import tkinter  # noqa: F401
            except Exception as exc:
                self._dead = True
                debug_log(f"bubble: tkinter unavailable ({exc!r}); bubble disabled")
                return False
            self._thread = threading.Thread(
                target=self._tk_main, name="plume-bubble", daemon=True
            )
            self._thread.start()
        self._ready.wait(5.0)
        if not self._ready.is_set():
            debug_log("bubble: Tk root not ready after 5s, skipping this one")
            return False
        return not self._dead

    def _post(self, fn) -> None:
        """Queue ``fn`` for execution on the Tk thread. Never raises."""
        try:
            if not self._ensure_thread():
                return
            self._q.put(fn)
        except Exception as exc:  # pragma: no cover - defensive
            debug_log(f"bubble: post failed ({exc!r})")

    def _tk_main(self) -> None:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            self._tk = tk
            self._root = root
            self._tk_ident = threading.get_ident()
        except Exception as exc:
            with self._lock:
                self._dead = True
            debug_log(f"bubble: Tk root creation failed ({exc!r})")
            self._ready.set()
            return

        self._ready.set()
        try:
            root.after(PUMP_MS, self._pump)
            root.mainloop()
        except Exception as exc:  # pragma: no cover - defensive
            debug_log(f"bubble: Tk main loop ended ({exc!r})")
        finally:
            with self._lock:
                self._dead = True

    def _pump(self) -> None:
        """Drain queued commands. Runs on the Tk thread only."""
        while True:
            try:
                fn = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as exc:
                debug_log(f"bubble: command failed ({exc!r})")
        if self._stopping:
            return
        try:
            self._root.after(PUMP_MS, self._pump)
        except Exception:
            pass

    # --- public API ----------------------------------------------------------
    def show(self, state: str = "listening", text: str = "À l'écoute…") -> None:
        self._post(lambda: self._do_show(state, text))

    def set_state(self, state: str, text: str = "") -> None:
        self._post(lambda: self._do_set_state(state, text))

    def set_level(self, level: float) -> None:
        try:
            self._level = max(0.0, min(1.0, float(level)))
        except Exception:
            self._level = 0.0

    def flash_done(self, text: str = "Collé", ms: int = 950) -> None:
        self._post(lambda: self._do_flash_done(text, ms))

    def hide(self) -> None:
        self._post(self._do_hide)

    def shutdown(self) -> None:
        with self._lock:
            if self._dead or self._thread is None:
                self._dead = True
                return
        self._post(self._do_shutdown)
        thread = self._thread
        if thread is not None:
            thread.join(2.0)
        with self._lock:
            self._dead = True

    # --- Tk thread: construction --------------------------------------------
    def _ensure_win(self) -> bool:
        """Create the window once. Idempotent -- show() twice must not stack."""
        if self._win is not None:
            return True
        tk = self._tk
        win = tk.Toplevel(self._root)
        self._win = win
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        try:
            win.attributes("-alpha", self._alpha)
        except Exception:
            pass
        canvas_bg = GLASS_BASE
        try:
            win.configure(bg=CHROMA)
            win.attributes("-transparentcolor", CHROMA)
            canvas_bg = CHROMA
        except Exception:
            try:
                win.configure(bg=GLASS_BASE)
            except Exception:
                pass
        win.withdraw()

        canvas = tk.Canvas(win, width=BUBBLE_W, height=BUBBLE_H,
                           highlightthickness=0, bd=0, bg=canvas_bg,
                           cursor="hand2")
        canvas.pack()
        self._canvas = canvas
        self._build(canvas)

        canvas.bind("<Button-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)

        _no_activate(win)
        return True

    def _build(self, canvas) -> None:
        """Construct multi-layer liquid glass / water drop optics."""
        cy = BUBBLE_H / 2.0
        cx_mid = BUBBLE_W / 2.0

        # 1. Ambient Contact Shadow beneath the droplet
        canvas.create_polygon(
            _rr_points(2, 6, BUBBLE_W - 2, BUBBLE_H, RADIUS),
            smooth=True, fill=SHADOW_DEPTH, outline="",
        )

        # 2. Smoked Liquid Glass Body
        canvas.create_polygon(
            _rr_points(2, 2, BUBBLE_W - 2, BUBBLE_H - 3, RADIUS),
            smooth=True, fill=GLASS_BASE, outline="",
        )

        # 3. Inner Liquid Volume / Refracted Depth Core
        canvas.create_polygon(
            _rr_points(4, 4, BUBBLE_W - 4, BUBBLE_H - 5, RADIUS - 2),
            smooth=True, fill=GLASS_CORE, outline="",
        )

        # 4. Top Convex Specular Glare (Signature Water Droplet Curvature)
        canvas.create_polygon(
            _specular_crescent_points(BUBBLE_W, BUBBLE_H, RADIUS),
            smooth=True, fill=GLASS_CRESCENT, outline="",
        )

        # 5. Specular Reflection Lines along the Upper Arc
        canvas.create_line(
            RADIUS * 0.7, 3.5, BUBBLE_W - RADIUS * 0.7, 3.5,
            fill=SPECULAR_TOP, width=1.5, capstyle="round",
        )
        canvas.create_line(
            cx_mid - 45, 3.5, cx_mid + 45, 3.5,
            fill=SPECULAR_PEAK, width=1.2, capstyle="round",
        )
        canvas.create_line(
            cx_mid - 15, 3.5, cx_mid + 15, 3.5,
            fill=SPECULAR_CORE, width=1.0, capstyle="round",
        )

        # 6. Bottom Caustic Refraction (Internal Lens Reflection)
        canvas.create_line(
            RADIUS * 0.9, BUBBLE_H - 4.5, BUBBLE_W - RADIUS * 0.9, BUBBLE_H - 4.5,
            fill=CAUSTIC_BOTTOM, width=1.2, capstyle="round",
        )

        # 7. Meniscus Surface Tension Rim (Crisp Glass Edge)
        canvas.create_polygon(
            _rr_points(2, 2, BUBBLE_W - 2, BUBBLE_H - 3, RADIUS),
            smooth=True, fill="", outline=MENISCUS_BORDER, width=1,
        )

        # 8. Liquid Status Droplet Bead (Glow Aura + Fluid Core + 3D Specular Highlight)
        self._dot_halo = canvas.create_oval(19, cy - 8, 37, cy + 8, fill=AURA_LIVE, outline="")
        self._dot = canvas.create_oval(23, cy - 5, 33, cy + 5, fill=LIVE_CORE, outline="")
        self._dot_spec = canvas.create_oval(25, cy - 3.5, 27.5, cy - 1.0, fill="#FFFFFF", outline="")

        # 9. Modern High-Contrast Typography
        self._label = canvas.create_text(
            48, cy - 0.5, anchor="w", fill=TEXT_LIVE,
            font=(FONT_UI, 11, "bold"), text="",
        )

        # 10. 7 Voice-Reactive Fluid Wave Ripples (Droplet Equalizer)
        self._bars = []
        total = (BAR_COUNT - 1) * BAR_GAP
        base_x = BUBBLE_W - 24 - total
        for i in range(BAR_COUNT):
            cx = base_x + i * BAR_GAP
            # Dynamic initial gradient: Center bars are luminous mint, flanking bars are teal
            dist_from_center = abs(i - (BAR_COUNT - 1) / 2.0)
            bar_fill = mix(LIVE_BAR_CENTER, LIVE_BAR_FLANK, dist_from_center / 3.0)
            item = canvas.create_polygon(
                _capsule_points(cx, cy, BAR_W / 2.0, BAR_W),
                smooth=True, fill=bar_fill, outline="",
            )
            self._bars.append((item, cx))

    # --- Tk thread: placement ------------------------------------------------
    def _place(self) -> None:
        win = self._win
        try:
            win.update_idletasks()
        except Exception:
            pass
        sw = int(self._root.winfo_screenwidth())
        sh = int(self._root.winfo_screenheight())
        left, top, right, bottom = _work_area(sw, sh)

        if self.pos is not None:
            x, y = int(self.pos[0]), int(self.pos[1])
        else:
            x = left + (right - left - BUBBLE_W) // 2
            y = top + MARGIN if self.position == "top" else bottom - BUBBLE_H - MARGIN

        vleft, vtop, vright, vbottom = _virtual_screen(sw, sh)
        x = max(vleft, min(x, vright - BUBBLE_W))
        y = max(vtop, min(y, vbottom - BUBBLE_H))
        win.geometry(f"{BUBBLE_W}x{BUBBLE_H}+{x}+{y}")

    # --- Tk thread: commands -------------------------------------------------
    def _do_show(self, state: str, text: str) -> None:
        self._ensure_win()
        self._cancel_hide()
        self._alpha = 0.96
        try:
            self._win.attributes("-alpha", self._alpha)
        except Exception:
            pass
        self._do_set_state(state, text)
        self._place()
        try:
            self._win.deiconify()
            self._win.lift()
            self._win.attributes("-topmost", True)
        except Exception as exc:
            debug_log(f"bubble: show failed ({exc!r})")
        self._visible = True
        if self._anim_id is None:
            self._tick()

    def _do_set_state(self, state: str, text: str) -> None:
        if state not in ("listening", "transcribing", "done"):
            state = "listening"
        self._state = state
        if self._canvas is None:
            return

        if state == "listening":
            self._canvas.itemconfigure(self._dot_halo, fill=AURA_LIVE)
            self._canvas.itemconfigure(self._dot, fill=LIVE_CORE)
            self._canvas.itemconfigure(self._dot_spec, fill="#FFFFFF")
            self._canvas.itemconfigure(self._label, fill=TEXT_LIVE)
            for i, (item, _cx) in enumerate(self._bars):
                dist = abs(i - (BAR_COUNT - 1) / 2.0)
                color = mix(LIVE_BAR_CENTER, LIVE_BAR_FLANK, dist / 3.0)
                self._canvas.itemconfigure(item, fill=color)
        elif state == "transcribing":
            self._canvas.itemconfigure(self._dot_halo, fill=AURA_SPIN)
            self._canvas.itemconfigure(self._dot, fill=SPIN_CORE)
            self._canvas.itemconfigure(self._dot_spec, fill="#FFFFFF")
            self._canvas.itemconfigure(self._label, fill=TEXT_SPIN)
            for item, _cx in self._bars:
                self._canvas.itemconfigure(item, fill=SPIN_BAR_DIM)
        elif state == "done":
            self._canvas.itemconfigure(self._dot_halo, fill=AURA_DONE)
            self._canvas.itemconfigure(self._dot, fill=DONE_CORE)
            self._canvas.itemconfigure(self._dot_spec, fill="#FFFFFF")
            self._canvas.itemconfigure(self._label, fill=TEXT_DONE)
            for item, _cx in self._bars:
                self._canvas.itemconfigure(item, fill=DONE_BAR)

        if text:
            self._canvas.itemconfigure(self._label, text=text)

    def _do_flash_done(self, text: str, ms: int) -> None:
        if self._win is None:
            self._do_show("done", text or "Collé")
        else:
            self._cancel_hide()
            self._do_set_state("done", text or "Collé")
            if not self._visible:
                self._place()
                self._alpha = 0.96
                try:
                    self._win.attributes("-alpha", self._alpha)
                    self._win.deiconify()
                    self._win.lift()
                except Exception:
                    pass
                self._visible = True
                if self._anim_id is None:
                    self._tick()
        try:
            self._hide_id = self._root.after(max(0, int(ms)), self._fade_out)
        except Exception:
            self._do_hide()

    def _do_hide(self) -> None:
        self._cancel_hide()
        self._visible = False
        self._state = "hidden"
        if self._anim_id is not None:
            try:
                self._root.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None
        if self._win is not None:
            try:
                self._win.withdraw()
            except Exception:
                pass

    def _do_shutdown(self) -> None:
        self._stopping = True
        self._do_hide()
        for obj in (self._win, self._root):
            try:
                if obj is not None:
                    obj.destroy()
            except Exception:
                pass
        self._win = None
        self._canvas = None
        try:
            self._root.quit()
        except Exception:
            pass

    def _cancel_hide(self) -> None:
        if self._hide_id is not None:
            try:
                self._root.after_cancel(self._hide_id)
            except Exception:
                pass
            self._hide_id = None

    # --- Tk thread: drag -----------------------------------------------------
    def _on_press(self, event) -> None:
        try:
            self._drag = (event.x, event.y)
            self._drag_moved = False
        except Exception:
            self._drag = None

    def _on_drag(self, event) -> None:
        if self._drag is None or self._win is None:
            return
        try:
            x = event.x_root - self._drag[0]
            y = event.y_root - self._drag[1]
            self._win.geometry(f"+{int(x)}+{int(y)}")
            self._drag_moved = True
        except Exception:
            pass

    def _on_release(self, event) -> None:
        moved = self._drag_moved
        self._drag = None
        self._drag_moved = False
        if not moved or self._win is None:
            return
        try:
            x = int(self._win.winfo_x())
            y = int(self._win.winfo_y())
        except Exception:
            return
        self.pos = (x, y)
        if self.on_move is not None:
            try:
                self.on_move(x, y)
            except Exception as exc:
                debug_log(f"bubble: on_move callback failed ({exc!r})")

    # --- Tk thread: animation & fluid dynamics -------------------------------
    def _targets(self) -> list[float]:
        floor = BAR_W / 2.0
        if self._state == "listening":
            level = self._level
            out = []
            center_idx = (BAR_COUNT - 1) / 2.0
            for i in range(BAR_COUNT):
                # Ripple dispersion across fluid surface
                ripple_phase = self._phase * 1.5 + (i - center_idx) * 0.6
                wave_shimmer = 0.45 + 0.55 * math.sin(ripple_phase)

                # Ambient living liquid breath (calm water surface)
                idle_breath = 1.2 + 0.9 * (0.5 + 0.5 * math.sin(self._phase * 0.8 + i * 0.45))

                # Fluid acoustic crest (parabolic center concentration)
                dist = abs(i - center_idx) / center_idx
                center_weight = 1.0 - 0.28 * (dist ** 2)
                voice_surge = level * BAR_MAX * wave_shimmer * center_weight

                out.append(floor + idle_breath + voice_surge)
            return out

        if self._state == "transcribing":
            # Silky continuous liquid traveling wave
            out = []
            head = (self._phase * 0.85) % (BAR_COUNT + 2) - 1
            for i in range(BAR_COUNT):
                d = abs(i - head)
                out.append(floor + 1.5 + 11.0 * math.exp(-(d * d) / 1.3))
            return out

        if self._state == "done":
            return [floor + 2.5] * BAR_COUNT

        return [floor] * BAR_COUNT

    def _tick(self) -> None:
        self._anim_id = None
        if not self._visible or self._canvas is None:
            return
        self._phase += 0.20
        cy = BUBBLE_H / 2.0

        try:
            # 1. Animate the Liquid Droplet Bead
            if self._state == "transcribing":
                # Oceanic liquid vortex orbit
                r = 2.8
                ox = 28.0 + r * math.cos(self._phase * 2.0)
                oy = cy + r * math.sin(self._phase * 2.0)
                pr = 4.0
                halo_r = pr + 3.5

                # Fluid chromatic shift during vortex
                hue_t = 0.5 + 0.5 * math.sin(self._phase * 1.5)
                vortex_color = mix(SPIN_CORE, SPIN_CORE_ALT, hue_t)
                self._canvas.itemconfigure(self._dot, fill=vortex_color)

            elif self._state == "done":
                # Crystalline confirmation flash
                pr = 5.8
                halo_r = 9.0
                ox, oy = 28.0, cy
            else:
                # Listening: breathing liquid droplet + reactive aura
                pr = 4.4 + 1.4 * (0.5 + 0.5 * math.sin(self._phase * 1.6)) + self._level * 1.6
                halo_r = pr + 3.2 + self._level * 4.5
                ox, oy = 28.0, cy

            # Update Droplet + Aura + Specular Pinpoint Coords
            self._canvas.coords(self._dot_halo, ox - halo_r, oy - halo_r, ox + halo_r, oy + halo_r)
            self._canvas.coords(self._dot, ox - pr, oy - pr, ox + pr, oy + pr)
            spec_r = pr * 0.32
            self._canvas.coords(
                self._dot_spec,
                ox - pr * 0.55 - spec_r, oy - pr * 0.55 - spec_r,
                ox - pr * 0.55 + spec_r, oy - pr * 0.55 + spec_r,
            )

            # 2. Animate Fluid Wave Ripples (Droplet Equalizer)
            targets = self._targets()
            head = (self._phase * 0.85) % (BAR_COUNT + 2) - 1
            for i, (item, cx) in enumerate(self._bars):
                target = targets[i]
                # Viscous fluid easing: fast crest rise, buoyant fluid descent
                ease = EASE_UP if target > self._bar_vals[i] else EASE_DOWN
                self._bar_vals[i] += (target - self._bar_vals[i]) * ease
                self._canvas.coords(
                    item, *_capsule_points(cx, cy, self._bar_vals[i], BAR_W)
                )

                # In transcribing mode, highlight the wave crest dynamically
                if self._state == "transcribing":
                    d = abs(i - head)
                    crest_t = max(0.0, 1.0 - d / 1.5)
                    bar_color = mix(SPIN_BAR_DIM, SPIN_BAR_ACTIVE, crest_t)
                    self._canvas.itemconfigure(item, fill=bar_color)

        except Exception as exc:
            debug_log(f"bubble: animation stopped ({exc!r})")
            return

        try:
            self._anim_id = self._root.after(FRAME_MS, self._tick)
        except Exception:
            self._anim_id = None

    def _fade_out(self) -> None:
        self._hide_id = None
        self._alpha -= 0.14
        if self._alpha <= 0.04 or self._win is None:
            self._do_hide()
            return
        try:
            self._win.attributes("-alpha", max(0.0, self._alpha))
        except Exception:
            self._do_hide()
            return
        try:
            self._hide_id = self._root.after(FRAME_MS, self._fade_out)
        except Exception:
            self._do_hide()
