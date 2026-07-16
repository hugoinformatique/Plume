"""A small floating "listening" bubble shown while Plume records/transcribes.

A frameless, always-on-top rounded pill centered near the top or bottom of the
screen with a smooth, voice-reactive equaliser. It deliberately never takes
focus, so the app you are dictating into stays active and the paste lands in
the right place.

Everything here must be called from the Tk main thread.
"""

from __future__ import annotations

import math

from ui_theme import ACCENT, BRAND, INK, INK_SOFT, TEXT

CHROMA = "#010101"  # transparent-color key for rounded corners on Windows

BUBBLE_W = 268
BUBBLE_H = 68
BAR_COUNT = 5
BAR_W = 7           # bar thickness (round caps make these pills)
BAR_GAP = 14
EASE = 0.35         # 0..1, higher = snappier; lower = smoother/floatier


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
        self.bar_vals: list[float] = [4.0] * BAR_COUNT
        self.dot = None
        self.label_id = None
        self._phase = 0.0
        self._anim_id = None
        self._hide_id = None
        self._state = "hidden"  # hidden | listening | transcribing | done
        self._level_provider = None

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
        try:
            self.win.configure(bg=CHROMA)
            self.win.attributes("-transparentcolor", CHROMA)
            canvas_bg = CHROMA
        except tk.TclError:
            canvas_bg = INK
        try:
            self.win.attributes("-disabled", True)  # never steal focus
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(
            self.win, width=BUBBLE_W, height=BUBBLE_H,
            highlightthickness=0, bg=canvas_bg,
        )
        self.canvas.pack()

        # Soft shadow-ish base + main pill for a bit more depth.
        _round_rect(self.canvas, 3, 5, BUBBLE_W - 3, BUBBLE_H - 2, 24, fill=INK_SOFT, outline="")
        _round_rect(self.canvas, 2, 2, BUBBLE_W - 2, BUBBLE_H - 5, 22, fill=INK, outline="")

        cy = (BUBBLE_H - 3) // 2
        # Pulsing status dot.
        self.dot = self.canvas.create_oval(22, cy - 5, 32, cy + 5, fill=ACCENT, outline="")
        # Status label.
        self.label_id = self.canvas.create_text(
            46, cy, anchor="w", fill=TEXT, font=("Segoe UI", 12, "bold"), text="",
        )
        # Equaliser bars (round-capped lines), right-aligned.
        total = (BAR_COUNT - 1) * BAR_GAP
        base_x = BUBBLE_W - 26 - total
        for i in range(BAR_COUNT):
            x = base_x + i * BAR_GAP
            bar = self.canvas.create_line(x, cy - 4, x, cy + 4, fill=ACCENT,
                                          width=BAR_W, capstyle="round")
            self.bars.append(bar)

    def _place(self) -> None:
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - BUBBLE_W) // 2
        y = 56 if self.position == "top" else sh - BUBBLE_H - 96
        self.win.geometry(f"{BUBBLE_W}x{BUBBLE_H}+{x}+{y}")

    # --- public API ----------------------------------------------------------
    def show(self, state: str = "listening", text: str = "A l'ecoute...", level_provider=None) -> None:
        self._ensure()
        if self._hide_id is not None:
            self.root.after_cancel(self._hide_id)
            self._hide_id = None
        self._level_provider = level_provider
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
        color = {"listening": ACCENT, "transcribing": BRAND, "done": ACCENT}.get(state, ACCENT)
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
        self._level_provider = None
        if self.win is not None:
            self.win.withdraw()

    def flash_done(self, text: str = "Colle", delay_ms: int = 900) -> None:
        if self.win is None:
            return
        self.set_state("done", text)
        if self._hide_id is not None:
            self.root.after_cancel(self._hide_id)
        self._hide_id = self.root.after(delay_ms, self.hide)

    # --- animation -----------------------------------------------------------
    def _targets(self) -> list[float]:
        # Keep half-heights within the pill (max ~26 for a 68px bubble).
        span = (BUBBLE_H - 3) * 0.34
        floor = 3.0
        if self._state == "listening":
            level = 0.0
            if self._level_provider is not None:
                try:
                    level = max(0.0, min(1.0, float(self._level_provider())))
                except Exception:
                    level = 0.0
            out = []
            for i in range(BAR_COUNT):
                shimmer = 0.55 + 0.45 * math.sin(self._phase * 1.3 + i * 0.7)
                out.append(floor + level * span * shimmer)
            return out
        if self._state == "transcribing":
            return [6 + 9 * (0.5 + 0.5 * math.sin(self._phase * 2 - i * 1.0)) for i in range(BAR_COUNT)]
        if self._state == "done":
            return [span * 0.8] * BAR_COUNT
        return [4.0] * BAR_COUNT

    def _animate(self) -> None:
        if self._state == "hidden":
            self._anim_id = None
            return
        self._phase += 0.22
        cy = (BUBBLE_H - 3) // 2

        # Dot: gentle pulse.
        pr = 4.5 + 1.8 * (0.5 + 0.5 * math.sin(self._phase * 1.7))
        self.canvas.coords(self.dot, 27 - pr, cy - pr, 27 + pr, cy + pr)

        # Bars: ease current values toward targets for fluid motion.
        targets = self._targets()
        for i, bar in enumerate(self.bars):
            self.bar_vals[i] += (targets[i] - self.bar_vals[i]) * EASE
            h = self.bar_vals[i]
            x1, _, _x2, _ = self.canvas.coords(bar)
            self.canvas.coords(bar, x1, cy - h, x1, cy + h)

        self._anim_id = self.root.after(33, self._animate)
