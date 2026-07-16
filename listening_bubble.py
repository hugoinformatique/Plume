"""A small floating "listening" bubble shown while Plume records/transcribes.

A frameless, always-on-top pill centered near the top or bottom of the screen
with an animated equaliser. It deliberately never takes focus, so the app you
are dictating into stays active and the final paste lands in the right place.

Everything here must be called from the Tk main thread.
"""

from __future__ import annotations

import math

from ui_theme import ACCENT, INK, MUTED, TEXT

CHROMA = "#010101"  # transparent-color key for rounded corners on Windows

BUBBLE_W = 264
BUBBLE_H = 66
BAR_COUNT = 5


def _round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class ListeningBubble:
    def __init__(self, root, position: str = "bottom") -> None:
        self.root = root
        self.position = position
        self.win = None
        self.canvas = None
        self.bars: list[int] = []
        self.dot = None
        self.label_id = None
        self._phase = 0.0
        self._anim_id = None
        self._hide_id = None
        self._state = "hidden"  # hidden | listening | transcribing | done

    # --- lifecycle -----------------------------------------------------------
    def _ensure(self) -> None:
        if self.win is not None:
            return
        import tkinter as tk

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        # Rounded corners: make the key colour transparent (Windows only).
        try:
            self.win.configure(bg=CHROMA)
            self.win.attributes("-transparentcolor", CHROMA)
            canvas_bg = CHROMA
        except tk.TclError:
            canvas_bg = INK
        # Do not let the bubble grab focus / steal the paste target.
        try:
            self.win.attributes("-disabled", True)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(
            self.win, width=BUBBLE_W, height=BUBBLE_H,
            highlightthickness=0, bg=canvas_bg,
        )
        self.canvas.pack()

        _round_rect(self.canvas, 1, 1, BUBBLE_W - 1, BUBBLE_H - 1, 20, fill=INK, outline="")

        # Pulsing status dot.
        self.dot = self.canvas.create_oval(24, BUBBLE_H // 2 - 6, 36, BUBBLE_H // 2 + 6,
                                           fill=ACCENT, outline="")
        # Status label.
        self.label_id = self.canvas.create_text(
            52, BUBBLE_H // 2, anchor="w", fill=TEXT,
            font=("Segoe UI", 12, "bold"), text="",
        )
        # Equaliser bars on the right.
        base_x = BUBBLE_W - 26 - (BAR_COUNT - 1) * 12
        cy = BUBBLE_H // 2
        for i in range(BAR_COUNT):
            x = base_x + i * 12
            bar = self.canvas.create_rectangle(x, cy - 4, x + 6, cy + 4, fill=ACCENT, outline="")
            self.bars.append(bar)

    def _place(self) -> None:
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - BUBBLE_W) // 2
        if self.position == "top":
            y = 56
        else:
            y = sh - BUBBLE_H - 96  # sit above the Windows taskbar
        self.win.geometry(f"{BUBBLE_W}x{BUBBLE_H}+{x}+{y}")

    # --- public API ----------------------------------------------------------
    def show(self, state: str = "listening", text: str = "À l'écoute…") -> None:
        self._ensure()
        if self._hide_id is not None:
            self.root.after_cancel(self._hide_id)
            self._hide_id = None
        self.set_state(state, text)
        self._place()
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        if self._anim_id is None:
            self._animate()

    def set_state(self, state: str, text: str | None = None) -> None:
        self._state = state
        if self.canvas is None:
            return
        colors = {"listening": ACCENT, "transcribing": "#5B6EF5", "done": ACCENT}
        color = colors.get(state, MUTED)
        self.canvas.itemconfigure(self.dot, fill=color)
        for bar in self.bars:
            self.canvas.itemconfigure(bar, fill=color)
        if text is not None:
            self.canvas.itemconfigure(self.label_id, text=text)

    def hide(self) -> None:
        if self._anim_id is not None:
            self.root.after_cancel(self._anim_id)
            self._anim_id = None
        if self._hide_id is not None:
            self.root.after_cancel(self._hide_id)
            self._hide_id = None
        self._state = "hidden"
        if self.win is not None:
            self.win.withdraw()

    def flash_done(self, text: str = "Collé ✓", delay_ms: int = 900) -> None:
        """Briefly confirm success, then auto-hide."""
        if self.win is None:
            return
        self.set_state("done", text)
        if self._hide_id is not None:
            self.root.after_cancel(self._hide_id)
        self._hide_id = self.root.after(delay_ms, self.hide)

    # --- animation -----------------------------------------------------------
    def _animate(self) -> None:
        if self._state in ("hidden",):
            self._anim_id = None
            return
        self._phase += 0.28
        cy = BUBBLE_H // 2

        # Dot: gentle pulse via size.
        pr = 5 + 2.2 * (0.5 + 0.5 * math.sin(self._phase * 1.6))
        self.canvas.coords(self.dot, 30 - pr, cy - pr, 30 + pr, cy + pr)

        # Bars: equaliser while listening, travelling wave while transcribing.
        for i, bar in enumerate(self.bars):
            x1, _, x2, _ = self.canvas.coords(bar)
            if self._state == "transcribing":
                amp = 3 + 8 * (0.5 + 0.5 * math.sin(self._phase * 2 - i * 1.1))
            elif self._state == "done":
                amp = 10
            else:  # listening
                amp = 3 + 12 * (0.5 + 0.5 * math.sin(self._phase + i * 0.9))
            self.canvas.coords(bar, x1, cy - amp, x2, cy + amp)

        self._anim_id = self.root.after(45, self._animate)
