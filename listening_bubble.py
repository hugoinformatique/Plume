"""A floating "listening" bubble shown while Plume records/transcribes (Tkinter legacy).

Liquid Glass / Water Droplet (Goutte d'eau) aesthetic:
A frameless, always-on-top translucent liquid glass pill with optical depth,
convex specular glares, volumetric refractions, a breathing 3D water-droplet bead,
and voice-reactive fluid wave ripples.

Everything here must be called from the Tk main thread.
"""

from __future__ import annotations

import math

from ui_theme import FONT_UI, mix

CHROMA = "#010101"       # transparent-color key for rounded corners on Windows

BUBBLE_W = 276
BUBBLE_H = 68
RADIUS = 30              # organic fluid pebble / water droplet curvature

BAR_COUNT = 7            # 7 voice-reactive fluid wave ripples
BAR_W = 5.0              # rounded droplet capsule width
BAR_GAP = 11.5
BAR_MAX = 19.0
EASE_UP = 0.38
EASE_DOWN = 0.22

# Liquid Glass / Water Droplet Optics Palette
SHADOW_DEPTH = "#030508"         # soft contact shadow beneath the droplet
GLASS_BASE = "#0C0F17"           # smoked liquid glass body
GLASS_CORE = "#121724"           # inner refracted liquid volume
GLASS_CRESCENT = "#192233"       # top convex meniscus glare polygon
SPECULAR_TOP = "#3B5270"         # soft top curvature highlight arc
SPECULAR_PEAK = "#82A7CF"        # bright light streak along the top rim
SPECULAR_CORE = "#E2F0FD"        # pure brilliance apex highlight
CAUSTIC_BOTTOM = "#172233"       # bottom internal caustic light reflection
MENISCUS_BORDER = "#2A384C"      # luminous glass surface tension rim

TEXT_LIVE = "#F8FAFC"
TEXT_SPIN = "#94A3B8"
TEXT_DONE = "#FFFFFF"

AURA_LIVE = "#063328"
LIVE_CORE = "#00F5B8"
LIVE_BAR_CENTER = "#00F5B8"
LIVE_BAR_FLANK = "#14B8A6"

AURA_SPIN = "#111C2E"
SPIN_CORE = "#38BDF8"
SPIN_CORE_ALT = "#818CF8"
SPIN_BAR_ACTIVE = "#38BDF8"
SPIN_BAR_DIM = "#1E293B"

AURA_DONE = "#0369A1"
DONE_CORE = "#FFFFFF"
DONE_BAR = "#FFFFFF"


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
            self.win.attributes("-alpha", 0.96)
        except tk.TclError:
            pass
        try:
            self.win.configure(bg=CHROMA)
            self.win.attributes("-transparentcolor", CHROMA)
            canvas_bg = CHROMA
        except tk.TclError:
            canvas_bg = GLASS_BASE
        try:
            self.win.attributes("-disabled", True)  # never steal focus
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(
            self.win, width=BUBBLE_W, height=BUBBLE_H,
            highlightthickness=0, bg=canvas_bg,
        )
        self.canvas.pack()

        cy = BUBBLE_H / 2.0
        cx_mid = BUBBLE_W / 2.0

        # 1. Ambient Contact Shadow beneath the droplet
        self.canvas.create_polygon(
            _rr_points(2, 6, BUBBLE_W - 2, BUBBLE_H, RADIUS),
            smooth=True, fill=SHADOW_DEPTH, outline="",
        )

        # 2. Smoked Liquid Glass Body
        self.canvas.create_polygon(
            _rr_points(2, 2, BUBBLE_W - 2, BUBBLE_H - 3, RADIUS),
            smooth=True, fill=GLASS_BASE, outline="",
        )

        # 3. Inner Liquid Volume / Refracted Depth Core
        self.canvas.create_polygon(
            _rr_points(4, 4, BUBBLE_W - 4, BUBBLE_H - 5, RADIUS - 2),
            smooth=True, fill=GLASS_CORE, outline="",
        )

        # 4. Top Convex Specular Glare (Signature Water Droplet Curvature)
        self.canvas.create_polygon(
            _specular_crescent_points(BUBBLE_W, BUBBLE_H, RADIUS),
            smooth=True, fill=GLASS_CRESCENT, outline="",
        )

        # 5. Specular Reflection Lines along the Upper Arc
        self.canvas.create_line(
            RADIUS * 0.7, 3.5, BUBBLE_W - RADIUS * 0.7, 3.5,
            fill=SPECULAR_TOP, width=1.5, capstyle="round",
        )
        self.canvas.create_line(
            cx_mid - 45, 3.5, cx_mid + 45, 3.5,
            fill=SPECULAR_PEAK, width=1.2, capstyle="round",
        )
        self.canvas.create_line(
            cx_mid - 15, 3.5, cx_mid + 15, 3.5,
            fill=SPECULAR_CORE, width=1.0, capstyle="round",
        )

        # 6. Bottom Caustic Refraction (Internal Lens Reflection)
        self.canvas.create_line(
            RADIUS * 0.9, BUBBLE_H - 4.5, BUBBLE_W - RADIUS * 0.9, BUBBLE_H - 4.5,
            fill=CAUSTIC_BOTTOM, width=1.2, capstyle="round",
        )

        # 7. Meniscus Surface Tension Rim (Crisp Glass Edge)
        self.canvas.create_polygon(
            _rr_points(2, 2, BUBBLE_W - 2, BUBBLE_H - 3, RADIUS),
            smooth=True, fill="", outline=MENISCUS_BORDER, width=1,
        )

        # 8. Liquid Status Droplet Bead
        self.dot_halo = self.canvas.create_oval(19, cy - 8, 37, cy + 8, fill=AURA_LIVE, outline="")
        self.dot = self.canvas.create_oval(23, cy - 5, 33, cy + 5, fill=LIVE_CORE, outline="")
        self.dot_spec = self.canvas.create_oval(25, cy - 3.5, 27.5, cy - 1.0, fill="#FFFFFF", outline="")

        # 9. Modern Typography
        self.label_id = self.canvas.create_text(
            48, cy - 0.5, anchor="w", fill=TEXT_LIVE,
            font=(FONT_UI, 11, "bold"), text="",
        )

        # 10. 7 Voice-Reactive Fluid Wave Ripples
        self.bars = []
        total = (BAR_COUNT - 1) * BAR_GAP
        base_x = BUBBLE_W - 24 - total
        for i in range(BAR_COUNT):
            cx = base_x + i * BAR_GAP
            dist_from_center = abs(i - (BAR_COUNT - 1) / 2.0)
            bar_fill = mix(LIVE_BAR_CENTER, LIVE_BAR_FLANK, dist_from_center / 3.0)
            item = self.canvas.create_polygon(
                _capsule_points(cx, cy, BAR_W / 2.0, BAR_W),
                smooth=True, fill=bar_fill, outline="",
            )
            self.bars.append((item, cx))

    def _place(self) -> None:
        self.win.update_idletasks()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x = (sw - BUBBLE_W) // 2
        y = 56 if self.position == "top" else sh - BUBBLE_H - 96
        self.win.geometry(f"{BUBBLE_W}x{BUBBLE_H}+{x}+{y}")

    # --- public API ----------------------------------------------------------
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
            for i, (item, _cx) in enumerate(self.bars):
                dist = abs(i - (BAR_COUNT - 1) / 2.0)
                color = mix(LIVE_BAR_CENTER, LIVE_BAR_FLANK, dist / 3.0)
                self.canvas.itemconfigure(item, fill=color)
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

    # --- animation -----------------------------------------------------------
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
                ripple_phase = self._phase * 1.5 + (i - center_idx) * 0.6
                wave_shimmer = 0.45 + 0.55 * math.sin(ripple_phase)
                idle_breath = 1.2 + 0.9 * (0.5 + 0.5 * math.sin(self._phase * 0.8 + i * 0.45))
                dist = abs(i - center_idx) / center_idx
                center_weight = 1.0 - 0.28 * (dist ** 2)
                voice_surge = level * BAR_MAX * wave_shimmer * center_weight
                out.append(floor + idle_breath + voice_surge)
            return out

        if self._state == "transcribing":
            out = []
            head = (self._phase * 0.85) % (BAR_COUNT + 2) - 1
            for i in range(BAR_COUNT):
                d = abs(i - head)
                out.append(floor + 1.5 + 11.0 * math.exp(-(d * d) / 1.3))
            return out

        if self._state == "done":
            return [floor + 2.5] * BAR_COUNT

        return [floor] * BAR_COUNT

    def _animate(self) -> None:
        if self._state == "hidden":
            self._anim_id = None
            return
        self._phase += 0.20
        cy = BUBBLE_H / 2.0

        try:
            # 1. Animate Liquid Droplet Bead
            if self._state == "transcribing":
                r = 2.8
                ox = 28.0 + r * math.cos(self._phase * 2.0)
                oy = cy + r * math.sin(self._phase * 2.0)
                pr = 4.0
                halo_r = pr + 3.5
                hue_t = 0.5 + 0.5 * math.sin(self._phase * 1.5)
                vortex_color = mix(SPIN_CORE, SPIN_CORE_ALT, hue_t)
                self.canvas.itemconfigure(self.dot, fill=vortex_color)
            elif self._state == "done":
                pr = 5.8
                halo_r = 9.0
                ox, oy = 28.0, cy
            else:
                level = 0.0
                if self._level_provider is not None:
                    try:
                        level = max(0.0, min(1.0, float(self._level_provider())))
                    except Exception:
                        level = 0.0
                pr = 4.4 + 1.4 * (0.5 + 0.5 * math.sin(self._phase * 1.6)) + level * 1.6
                halo_r = pr + 3.2 + level * 4.5
                ox, oy = 28.0, cy

            self.canvas.coords(self.dot_halo, ox - halo_r, oy - halo_r, ox + halo_r, oy + halo_r)
            self.canvas.coords(self.dot, ox - pr, oy - pr, ox + pr, oy + pr)
            spec_r = pr * 0.32
            self.canvas.coords(
                self.dot_spec,
                ox - pr * 0.55 - spec_r, oy - pr * 0.55 - spec_r,
                ox - pr * 0.55 + spec_r, oy - pr * 0.55 + spec_r,
            )

            # 2. Animate Fluid Wave Ripples
            targets = self._targets()
            head = (self._phase * 0.85) % (BAR_COUNT + 2) - 1
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

        self._anim_id = self.root.after(33, self._animate)
