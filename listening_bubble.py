"""A floating "listening" bubble shown while Plume records/transcribes (Tkinter legacy).

Liquid Glass / Water Droplet (Goutte d'eau) aesthetic:
Strictly achromatic monochrome palette (pure blacks, smoked glass depths,
convex specular highlights, and crisp pure whites). No hue/color accents.
Ultra-fluid 120Hz-ready animation loop with viscous liquid wave physics.
DPI-aware rendering for crisp display on HiDPI screens.

Everything here must be called from the Tk main thread.
"""

from __future__ import annotations

import math
import sys

from ui_theme import FONT_UI, mix

# --- Windows DPI awareness ---------------------------------------------------
def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass

_enable_dpi_awareness()

CHROMA = "#010101"

BUBBLE_W = 200
BUBBLE_H = 48
RADIUS = 21

BAR_COUNT = 5
BAR_W = 3.5
BAR_GAP = 8.0
BAR_MAX = 13.0

FRAME_MS = 12
EASE_UP = 0.26
EASE_DOWN = 0.14

# Strictly Achromatic Liquid Glass Monochrome Palette
SHADOW_DEPTH = "#000000"
GLASS_BASE = "#0F0F0F"
GLASS_INNER = "#171717"
GLASS_DOME = "#222222"
SPECULAR_CRESCENT = "#2C2C2C"
SPECULAR_ARC = "#555555"
SPECULAR_STREAK = "#AAAAAA"
SPECULAR_APEX = "#FFFFFF"
CAUSTIC_LIP = "#242424"
MENISCUS_BORDER = "#3A3A3A"

TEXT_LIVE = "#FFFFFF"
TEXT_SPIN = "#8E8E8E"
TEXT_DONE = "#FFFFFF"

AURA_LIVE = "#242424"
LIVE_CORE = "#FFFFFF"
LIVE_BAR = "#FFFFFF"

AURA_SPIN = "#1C1C1C"
SPIN_CORE = "#B0B0B0"
SPIN_BAR_ACTIVE = "#FFFFFF"
SPIN_BAR_DIM = "#3A3A3A"

AURA_DONE = "#333333"
DONE_CORE = "#FFFFFF"
DONE_BAR = "#FFFFFF"

DOT_CX = 20.0


def _rr_points(x1: float, y1: float, x2: float, y2: float, r: float) -> list[float]:
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def _capsule_points(cx: float, cy: float, half_h: float, w: float) -> list[float]:
    half_w = w / 2.0
    half_h = max(half_h, half_w)
    return _rr_points(cx - half_w, cy - half_h, cx + half_w, cy + half_h, half_w)


def _specular_crescent_points(w: float, h: float, r: float) -> list[float]:
    x1, y1, x2, y2 = 3.0, 2.0, w - 3.0, h * 0.40
    cr = r * 0.85
    return [
        x1 + cr, y1,
        x2 - cr, y1,
        x2, y1 + cr * 0.4,
        x2 - cr * 0.5, y2,
        w / 2.0, y2 + 1.0,
        x1 + cr * 0.5, y2,
        x1, y1 + cr * 0.4,
    ]


class ListeningBubble:
    def __init__(self, root, position: str = "bottom") -> None:
        self.root = root
        self.position = position
        self.win = None
        self.canvas = None
        self.bars: list[tuple[int, float]] = []
        self.bar_vals: list[float] = [BAR_W / 2.0] * BAR_COUNT
        self.dot_halo = None
        self.dot = None
        self.dot_spec = None
        self.label_id = None
        self._phase = 0.0
        self._anim_id = None
        self._hide_id = None
        self._state = "hidden"
        self._level_provider = None

    def _ensure(self) -> None:
        if self.win is not None:
            return
        import tkinter as tk

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-alpha", 0.96)
        except tk.TclError:
            pass
        # Crisp text at native DPI
        try:
            self.root.tk.call("tk", "scaling", self.root.winfo_fpixels("1i") / 72.0)
        except Exception:
            pass
        try:
            self.win.configure(bg=CHROMA)
            self.win.attributes("-transparentcolor", CHROMA)
            canvas_bg = CHROMA
        except tk.TclError:
            canvas_bg = GLASS_BASE
        try:
            self.win.attributes("-disabled", True)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(
            self.win, width=BUBBLE_W, height=BUBBLE_H,
            highlightthickness=0, bg=canvas_bg,
        )
        self.canvas.pack()

        cy = BUBBLE_H / 2.0
        cx_mid = BUBBLE_W / 2.0

        # 1. Shadow
        self.canvas.create_polygon(
            _rr_points(1.5, 4, BUBBLE_W - 1.5, BUBBLE_H, RADIUS),
            smooth=True, fill=SHADOW_DEPTH, outline="",
        )

        # 2. Glass Body
        self.canvas.create_polygon(
            _rr_points(1.5, 1.5, BUBBLE_W - 1.5, BUBBLE_H - 2, RADIUS),
            smooth=True, fill=GLASS_BASE, outline="",
        )

        # 3. Inner Volume
        self.canvas.create_polygon(
            _rr_points(3, 3, BUBBLE_W - 3, BUBBLE_H - 3.5, RADIUS - 1.5),
            smooth=True, fill=GLASS_INNER, outline="",
        )

        # 4. Specular Crescent
        self.canvas.create_polygon(
            _specular_crescent_points(BUBBLE_W, BUBBLE_H, RADIUS),
            smooth=True, fill=SPECULAR_CRESCENT, outline="",
        )

        # 5. Specular Lines
        self.canvas.create_line(
            RADIUS * 0.7, 2.5, BUBBLE_W - RADIUS * 0.7, 2.5,
            fill=SPECULAR_ARC, width=1.0, capstyle="round",
        )
        self.canvas.create_line(
            cx_mid - 32, 2.5, cx_mid + 32, 2.5,
            fill=SPECULAR_STREAK, width=0.8, capstyle="round",
        )
        self.canvas.create_line(
            cx_mid - 14, 2.5, cx_mid + 14, 2.5,
            fill=SPECULAR_APEX, width=0.6, capstyle="round",
        )

        # 6. Bottom Caustic
        self.canvas.create_line(
            RADIUS * 0.9, BUBBLE_H - 3.5, BUBBLE_W - RADIUS * 0.9, BUBBLE_H - 3.5,
            fill=CAUSTIC_LIP, width=0.8, capstyle="round",
        )

        # 7. Meniscus Rim
        self.canvas.create_polygon(
            _rr_points(1.5, 1.5, BUBBLE_W - 1.5, BUBBLE_H - 2, RADIUS),
            smooth=True, fill="", outline=MENISCUS_BORDER, width=1,
        )

        # 8. Status Droplet Bead
        self.dot_halo = self.canvas.create_oval(
            DOT_CX - 7, cy - 7, DOT_CX + 7, cy + 7, fill=AURA_LIVE, outline="")
        self.dot = self.canvas.create_oval(
            DOT_CX - 4, cy - 4, DOT_CX + 4, cy + 4, fill=LIVE_CORE, outline="")
        self.dot_spec = self.canvas.create_oval(
            DOT_CX - 2.5, cy - 3, DOT_CX - 0.5, cy - 1, fill="#FFFFFF", outline="")

        # 9. Typography
        self.label_id = self.canvas.create_text(
            36, cy, anchor="w", fill=TEXT_LIVE,
            font=(FONT_UI, 9, "bold"), text="",
        )

        # 10. Wave Ripples
        self.bars = []
        total = (BAR_COUNT - 1) * BAR_GAP
        base_x = BUBBLE_W - 16 - total
        for i in range(BAR_COUNT):
            cx = base_x + i * BAR_GAP
            item = self.canvas.create_polygon(
                _capsule_points(cx, cy, BAR_W / 2.0, BAR_W),
                smooth=True, fill=LIVE_BAR, outline="",
            )
            self.bars.append((item, cx))

    def _place(self) -> None:
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - BUBBLE_W) // 2
        y = 48 if self.position == "top" else sh - BUBBLE_H - 80
        self.win.geometry(f"{BUBBLE_W}x{BUBBLE_H}+{x}+{y}")

    def show(self, state: str = "listening", text: str = "À l'écoute…", level_provider=None) -> None:
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
        if state not in ("listening", "transcribing", "done"):
            state = "listening"
        self._state = state
        if self.canvas is None:
            return

        if state == "listening":
            self.canvas.itemconfigure(self.dot_halo, fill=AURA_LIVE)
            self.canvas.itemconfigure(self.dot, fill=LIVE_CORE)
            self.canvas.itemconfigure(self.dot_spec, fill="#FFFFFF")
            self.canvas.itemconfigure(self.label_id, fill=TEXT_LIVE)
            for item, _cx in self.bars:
                self.canvas.itemconfigure(item, fill=LIVE_BAR)
        elif state == "transcribing":
            self.canvas.itemconfigure(self.dot_halo, fill=AURA_SPIN)
            self.canvas.itemconfigure(self.dot, fill=SPIN_CORE)
            self.canvas.itemconfigure(self.dot_spec, fill="#FFFFFF")
            self.canvas.itemconfigure(self.label_id, fill=TEXT_SPIN)
            for item, _cx in self.bars:
                self.canvas.itemconfigure(item, fill=SPIN_BAR_DIM)
        elif state == "done":
            self.canvas.itemconfigure(self.dot_halo, fill=AURA_DONE)
            self.canvas.itemconfigure(self.dot, fill=DONE_CORE)
            self.canvas.itemconfigure(self.dot_spec, fill="#FFFFFF")
            self.canvas.itemconfigure(self.label_id, fill=TEXT_DONE)
            for item, _cx in self.bars:
                self.canvas.itemconfigure(item, fill=DONE_BAR)

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

    def flash_done(self, text: str = "Collé", delay_ms: int = 950) -> None:
        if self.win is None:
            return
        self.set_state("done", text)
        if self._hide_id is not None:
            self.root.after_cancel(self._hide_id)
        self._hide_id = self.root.after(delay_ms, self.hide)

    def _targets(self) -> list[float]:
        floor = BAR_W / 2.0
        if self._state == "listening":
            level = 0.0
            if self._level_provider is not None:
                try:
                    level = max(0.0, min(1.0, float(self._level_provider())))
                except Exception:
                    level = 0.0
            out = []
            center_idx = (BAR_COUNT - 1) / 2.0
            for i in range(BAR_COUNT):
                ripple_phase = self._phase * 1.3 + (i - center_idx) * 0.55
                wave_shimmer = 0.50 + 0.50 * math.sin(ripple_phase)
                idle_breath = 1.1 + 0.8 * (0.5 + 0.5 * math.sin(self._phase * 0.7 + i * 0.4))
                dist = abs(i - center_idx) / center_idx
                center_weight = 1.0 - 0.28 * (dist ** 2)
                voice_surge = level * BAR_MAX * wave_shimmer * center_weight
                out.append(floor + idle_breath + voice_surge)
            return out

        if self._state == "transcribing":
            out = []
            head = (self._phase * 0.75) % (BAR_COUNT + 2) - 1
            for i in range(BAR_COUNT):
                d = abs(i - head)
                out.append(floor + 1.2 + 10.5 * math.exp(-(d * d) / 1.3))
            return out

        if self._state == "done":
            return [floor + 2.2] * BAR_COUNT

        return [floor] * BAR_COUNT

    def _animate(self) -> None:
        if self._state == "hidden":
            self._anim_id = None
            return
        self._phase += 0.12
        cy = BUBBLE_H / 2.0

        try:
            if self._state == "transcribing":
                r = 2.0
                ox = DOT_CX + r * math.cos(self._phase * 1.8)
                oy = cy + r * math.sin(self._phase * 1.8)
                pr = 3.2
                halo_r = pr + 2.8
            elif self._state == "done":
                pr = 4.5
                halo_r = 7.0
                ox, oy = DOT_CX, cy
            else:
                level = 0.0
                if self._level_provider is not None:
                    try:
                        level = max(0.0, min(1.0, float(self._level_provider())))
                    except Exception:
                        level = 0.0
                pr = 3.5 + 1.0 * (0.5 + 0.5 * math.sin(self._phase * 1.4)) + level * 1.2
                halo_r = pr + 2.5 + level * 3.0
                ox, oy = DOT_CX, cy

            self.canvas.coords(self.dot_halo, ox - halo_r, oy - halo_r, ox + halo_r, oy + halo_r)
            self.canvas.coords(self.dot, ox - pr, oy - pr, ox + pr, oy + pr)
            spec_r = pr * 0.28
            self.canvas.coords(
                self.dot_spec,
                ox - pr * 0.50 - spec_r, oy - pr * 0.50 - spec_r,
                ox - pr * 0.50 + spec_r, oy - pr * 0.50 + spec_r,
            )

            targets = self._targets()
            head = (self._phase * 0.75) % (BAR_COUNT + 2) - 1
            for i, (item, cx) in enumerate(self.bars):
                target = targets[i]
                ease = EASE_UP if target > self.bar_vals[i] else EASE_DOWN
                self.bar_vals[i] += (target - self.bar_vals[i]) * ease
                self.canvas.coords(
                    item, *_capsule_points(cx, cy, self.bar_vals[i], BAR_W)
                )
                if self._state == "transcribing":
                    d = abs(i - head)
                    crest_t = max(0.0, 1.0 - d / 1.5)
                    bar_color = mix(SPIN_BAR_DIM, SPIN_BAR_ACTIVE, crest_t)
                    self.canvas.itemconfigure(item, fill=bar_color)

        except Exception:
            return

        self._anim_id = self.root.after(FRAME_MS, self._animate)
