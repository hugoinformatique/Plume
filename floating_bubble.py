"""Native Tk floating "listening" bubble, self-contained and thread-safe.

Plume's main thread belongs to ``webview.start()``, so this module owns its
*own* Tk root running in its own daemon thread. Every public method may be
called from any thread (hotkey listener, transcription worker, pywebview
bridge): work is marshalled onto the Tk thread through a queue drained by a
small poller, so no Tk object is ever touched from outside that thread.

It is deliberately defensive. If tkinter is missing, or the root cannot be
created, or any Tk call blows up, the bubble silently becomes a no-op and the
dictation keeps working -- a decoration must never take the app down.

Replaces the old pywebview transparent-frameless secondary window
(``ui/bubble.html``), which never actually showed up on Windows.

Note: ``listening_bubble.py`` is the older sibling of this file; it is still
used by ``tray_app.py``, which owns a Tk main loop of its own.
"""

from __future__ import annotations

import math
import queue
import threading

from config import debug_log
from ui_theme import FONT_UI, mix

# --- geometry / look ---------------------------------------------------------
CHROMA = "#010101"       # transparent-color key -> rounded corners on Windows
BUBBLE_W = 260
BUBBLE_H = 64
RADIUS = 26
MARGIN = 40              # distance from the top/bottom edge of the work area

BAR_COUNT = 6
BAR_W = 6
BAR_GAP = 13
BAR_MAX = 18.0           # half-height, keeps bars inside the pill
EASE = 0.30              # 0..1, lower = smoother/floatier

FRAME_MS = 33            # ~30 fps
PUMP_MS = 30             # cross-thread command poll (cheap, not a busy loop)

# Strictly achromatic, like the window (ui_theme's INK/TEXT/MUTED are slightly
# blue-tinted, which is what made the pill read as "not the same product").
# States are told apart by value and motion, never by hue.
INK = "#121212"                      # pill body
INK_SOFT = "#1C1C1C"
TEXT = "#F2F2F2"                     # label
MUTED = "#949494"                    # label while transcribing
BORDER = mix(INK, "#FFFFFF", 0.14)
TOP_LIGHT = mix(INK_SOFT, "#FFFFFF", 0.10)
BOTTOM_EDGE = mix(INK, "#000000", 0.55)
LIVE = "#FFFFFF"                     # "listening" bars and dot
DIM = mix("#FFFFFF", INK, 0.55)      # "transcribing" bars: calm, dimmed
SPIN = mix("#FFFFFF", INK, 0.25)     # "transcribing" dot
DONE = "#FFFFFF"                     # confirmation


def _rr_points(x1: float, y1: float, x2: float, y2: float, r: float) -> list[float]:
    """Corner points for a rounded rectangle drawn as a ``smooth=True`` polygon.

    Duplicating the corner anchors is the classic Tk trick: the spline then
    hugs the corners instead of rounding the whole shape into a blob.
    """
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
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
    """(left, top, right, bottom) of the whole virtual desktop.

    Used to clamp a dragged position: `winfo_screenwidth/height` only covers
    the *primary* monitor, so a bubble dropped on a second screen used to be
    snapped back to the first one on the next dictation (and a monitor placed
    left of or above the primary gives negative coordinates, which clamped to
    the top-left corner).
    """
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
        # Explicit signatures: with the default int restype a 64-bit HWND
        # would be truncated, and the only symptom would be the pill stealing
        # focus -- i.e. the paste landing in the wrong window.
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
        # Not fatal, but worth knowing about: this is what keeps the paste in
        # the user's own window.
        debug_log(f"bubble: could not set WS_EX_NOACTIVATE: {type(exc).__name__}: {exc}")


class FloatingBubble:
    """A small always-on-top pill showing dictation state.

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
        self._bars: list = []
        self._bar_vals: list[float] = [BAR_W / 2.0] * BAR_COUNT
        self._dot = None
        self._label = None
        self._state = "hidden"
        self._visible = False
        self._phase = 0.0
        self._anim_id = None
        self._hide_id = None
        self._alpha = 0.96
        self._drag: tuple[int, int] | None = None
        self._drag_moved = False

        # Written from any thread, read from the Tk thread (float store is atomic).
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
            # Slow cold start (frozen build, antivirus scanning tcl/tk): don't
            # latch this as a permanent failure -- the thread is still coming
            # up, and the next dictation will find it ready. Latching here is
            # precisely how a bubble ends up never appearing again.
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
        # Called ~14x/s: do not queue anything, just store. The animation loop
        # samples this value on the Tk thread.
        try:
            self._level = max(0.0, min(1.0, float(level)))
        except Exception:
            self._level = 0.0

    def flash_done(self, text: str = "Collé", ms: int = 900) -> None:
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
        canvas_bg = INK
        try:
            win.configure(bg=CHROMA)
            win.attributes("-transparentcolor", CHROMA)
            canvas_bg = CHROMA
        except Exception:
            try:
                win.configure(bg=INK)
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
        cy = BUBBLE_H / 2.0

        # Fake depth: a darker sliver peeking under the body ...
        canvas.create_polygon(_rr_points(2, 5, BUBBLE_W - 2, BUBBLE_H - 1, RADIUS),
                              smooth=True, fill=BOTTOM_EDGE, outline="")
        # ... the glassy body itself ...
        canvas.create_polygon(_rr_points(2, 2, BUBBLE_W - 2, BUBBLE_H - 3, RADIUS),
                              smooth=True, fill=INK, outline="")
        # ... a 1 px lighter line along the top (light comes from above) ...
        canvas.create_line(2 + RADIUS * 0.7, 3, BUBBLE_W - 2 - RADIUS * 0.7, 3,
                           fill=TOP_LIGHT, width=1)
        # ... and a hairline white-ish border at low opacity.
        canvas.create_polygon(_rr_points(2, 2, BUBBLE_W - 2, BUBBLE_H - 3, RADIUS),
                              smooth=True, fill="", outline=BORDER, width=1)

        self._dot = canvas.create_oval(22, cy - 5, 32, cy + 5, fill=LIVE, outline="")
        self._label = canvas.create_text(46, cy - 1, anchor="w", fill=TEXT,
                                         font=(FONT_UI, 11, "bold"), text="")

        self._bars = []
        total = (BAR_COUNT - 1) * BAR_GAP
        base_x = BUBBLE_W - 24 - total
        for i in range(BAR_COUNT):
            cx = base_x + i * BAR_GAP
            item = canvas.create_polygon(
                _capsule_points(cx, cy, BAR_W / 2.0, BAR_W),
                smooth=True, fill=LIVE, outline="",
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

        # Clamp to the whole virtual desktop, not just the primary monitor: a
        # position saved on a screen that is no longer attached must not make
        # the bubble disappear, but a second attached screen must stay valid.
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
        color = {"listening": LIVE, "transcribing": DIM, "done": DONE}[state]
        dot = {"listening": LIVE, "transcribing": SPIN, "done": DONE}[state]
        for item, _cx in self._bars:
            self._canvas.itemconfigure(item, fill=color)
        self._canvas.itemconfigure(self._dot, fill=dot)
        self._canvas.itemconfigure(
            self._label, fill=MUTED if state == "transcribing" else TEXT
        )
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
                # Reset the opacity a previous fade-out may have left near 0,
                # otherwise the confirmation shows up invisible.
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
        # Debounced by construction: only the drag *end* notifies the caller.
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

    # --- Tk thread: animation ------------------------------------------------
    def _targets(self) -> list[float]:
        floor = BAR_W / 2.0
        if self._state == "listening":
            level = self._level
            out = []
            for i in range(BAR_COUNT):
                shimmer = 0.55 + 0.45 * math.sin(self._phase * 1.3 + i * 0.7)
                # Idle still breathes a little instead of freezing flat.
                breath = 1.2 + 0.9 * (0.5 + 0.5 * math.sin(self._phase * 0.9 + i * 0.5))
                out.append(floor + breath + level * BAR_MAX * shimmer)
            return out
        if self._state == "transcribing":
            # Calm left-to-right sweep.
            out = []
            head = (self._phase * 0.9) % (BAR_COUNT + 2) - 1
            for i in range(BAR_COUNT):
                d = abs(i - head)
                out.append(floor + 1.5 + 10.0 * math.exp(-(d * d) / 1.1))
            return out
        if self._state == "done":
            return [floor + 2.0] * BAR_COUNT
        return [floor] * BAR_COUNT

    def _tick(self) -> None:
        self._anim_id = None
        if not self._visible or self._canvas is None:
            return
        self._phase += 0.22
        cy = BUBBLE_H / 2.0

        try:
            if self._state == "transcribing":
                # Small orbit: reads as "processing", not "listening".
                r, pr = 3.0, 4.0
                ox = 27 + r * math.cos(self._phase * 2.2)
                oy = cy + r * math.sin(self._phase * 2.2)
            else:
                pr = 4.5 + 1.8 * (0.5 + 0.5 * math.sin(self._phase * 1.7))
                if self._state == "done":
                    pr = 6.0
                ox, oy = 27.0, cy
            self._canvas.coords(self._dot, ox - pr, oy - pr, ox + pr, oy + pr)

            targets = self._targets()
            for i, (item, cx) in enumerate(self._bars):
                self._bar_vals[i] += (targets[i] - self._bar_vals[i]) * EASE
                self._canvas.coords(
                    item, *_capsule_points(cx, cy, self._bar_vals[i], BAR_W)
                )
        except Exception as exc:
            debug_log(f"bubble: animation stopped ({exc!r})")
            return

        try:
            self._anim_id = self._root.after(FRAME_MS, self._tick)
        except Exception:
            self._anim_id = None

    def _fade_out(self) -> None:
        self._hide_id = None
        self._alpha -= 0.16
        if self._alpha <= 0.05 or self._win is None:
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
