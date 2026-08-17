"""Native floating "listening" bubble: real translucent glass, thread-safe.

Rendering
---------
The bubble is drawn with Pillow into an RGBA image and pushed to a Windows
*layered window* through ``UpdateLayeredWindow``. That is what makes it look
like glass rather than a black pebble:

- **Per-pixel alpha.** The desktop genuinely shows through the body, and the
  rounded edge fades over a pixel instead of being cut on a colour key. The
  previous implementation drew Tk canvas polygons on a window keyed with
  ``-transparentcolor``: Tk's canvas has no antialiasing and a colour key is
  1-bit transparency, so every curve came out as a staircase -- the
  "pixelated" bubble. No amount of DPI awareness could fix that, because the
  jagged edges were not a scaling artefact.
- **Nothing is read back from the screen.** The glass is translucent, not
  blurred: a blur would mean capturing the pixels behind the window, i.e.
  giving a dictation app a screen-capture capability, which is not something
  to hand a security review for a decoration. See docs/SECURITY.md.

Threading
---------
Plume's main thread belongs to ``webview.start()``, so this module owns its
*own* Tk root (used purely as a window + event source) running in its own
daemon thread. Every public method may be called from any thread: work is
marshalled onto that thread through a queue, so no Tk object is ever touched
from outside it.

It is deliberately defensive. If tkinter or Pillow is missing, or any call
blows up, the bubble silently becomes a no-op and dictation keeps working --
a decoration must never take the app down.
"""

from __future__ import annotations

import math
import queue
import sys
import threading

from config import debug_log


# --- Windows DPI awareness (must be called BEFORE any Tk window) ------------
def _enable_dpi_awareness() -> None:
    """Tell Windows to render at native DPI instead of bitmap-upscaling."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # Per-Monitor DPI Aware v2 (Windows 10 1703+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass


_enable_dpi_awareness()


# --- Geometry, in logical units at 96 dpi ------------------------------------
BUBBLE_W = 200           # compact pill width
BUBBLE_H = 48            # pill height
RADIUS = 24              # fully rounded ends: r == h/2 reads as a droplet
PAD = 16                 # room around the pill for the drop shadow
MARGIN = 36              # distance from the top/bottom edge of the work area
PREVIEW_W_MAX = 560      # the pill may grow this wide to show recognised text

BAR_COUNT = 5
BAR_W = 3.5
BAR_GAP = 8.0
BAR_MAX = 13.0

SS = 2                   # supersampling factor: everything is drawn at SSx
FRAME_MS = 25            # ~40 fps; each frame is a full re-render + blit
PUMP_MS = 25             # cross-thread command poll
EASE_UP = 0.26           # viscous crest rise
EASE_DOWN = 0.14         # buoyant descent


# --- Palette: strictly achromatic, now with real alpha -----------------------
# (r, g, b, a). The alpha is the whole point: GLASS_FILL at 60% is what lets
# the desktop through, where the old build used an opaque near-black fill.
GLASS_FILL = (16, 17, 20, 152)        # smoked glass body
GLASS_TOP = (255, 255, 255, 30)       # convex dome sheen, fades downward
GLASS_BOTTOM = (255, 255, 255, 10)    # faint bottom bounce
RIM_TOP = (255, 255, 255, 110)        # lit upper edge (surface tension)
RIM_BOTTOM = (255, 255, 255, 38)      # shaded lower edge
SHADOW = (0, 0, 0, 96)                # contact shadow under the droplet
STREAK = (255, 255, 255, 64)          # specular streak across the dome

TEXT_LIVE = (255, 255, 255, 245)
TEXT_SPIN = (255, 255, 255, 165)
TEXT_DONE = (255, 255, 255, 245)
TEXT_PREVIEW = (255, 255, 255, 215)

BEAD_CORE = (255, 255, 255, 250)
BEAD_HALO = (255, 255, 255, 40)
BEAD_SPEC = (255, 255, 255, 255)
BAR_LIVE = (255, 255, 255, 235)
BAR_DIM = (255, 255, 255, 70)

_STATES = ("listening", "transcribing", "preview", "done")


def _lerp_rgba(a, b, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(4))


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


def _load_font(px: int, bold: bool = True):
    """Best available UI font at `px` pixels, never raising."""
    from PIL import ImageFont

    names = (
        ["segoeuisb.ttf", "segoeuib.ttf", "segoeui.ttf"] if bold else ["segoeui.ttf"]
    ) + ["arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, px)
        except Exception:
            continue
    try:
        return ImageFont.load_default(px)
    except Exception:
        return ImageFont.load_default()


# --- Pure rendering (no Tk, no Windows API: unit-testable) -------------------
class GlassRenderer:
    """Draws the bubble into an RGBA image. Stateless between calls."""

    def __init__(self, width: int = BUBBLE_W, height: int = BUBBLE_H,
                 radius: int = RADIUS, pad: int = PAD, scale: float = 1.0) -> None:
        self.scale = max(0.5, float(scale))
        self.width = int(round(width * self.scale))
        self.height = int(round(height * self.scale))
        self.radius = int(round(radius * self.scale))
        self.pad = int(round(pad * self.scale))
        self.canvas_w = self.width + 2 * self.pad
        self.canvas_h = self.height + 2 * self.pad
        self._shell_cache: dict = {}
        self._font_cache: dict = {}

    # -- helpers ----------------------------------------------------------
    def font(self, logical_px: float, bold: bool = True):
        key = (round(logical_px * self.scale), bold)
        if key not in self._font_cache:
            self._font_cache[key] = _load_font(max(6, key[0]), bold)
        return self._font_cache[key]

    def text_width(self, text: str, logical_px: float = 12.5) -> float:
        """Width of `text` in logical units, for pill auto-sizing."""
        from PIL import Image, ImageDraw

        font = self.font(logical_px)
        draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        try:
            box = draw.textbbox((0, 0), text, font=font)
            return (box[2] - box[0]) / self.scale
        except Exception:
            return len(text) * logical_px * 0.55

    def _rounded(self, draw, box, radius, fill, outline=None, width=1) -> None:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

    def _layer(self, size):
        """A transparent scratch layer + its draw handle.

        Everything semi-transparent has to be drawn on one of these and then
        `alpha_composite`d: ImageDraw *writes* RGBA values, alpha included, so
        drawing a 40-alpha halo straight onto the glass does not glaze it --
        it punches a hole through it, and the desktop shows through the middle
        of the bead. That was the ring-shaped artefact around the indicator.
        """
        from PIL import Image, ImageDraw

        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        return layer, ImageDraw.Draw(layer)

    # -- the static glass shell (cached: it only changes with size) --------
    def shell(self) -> "object":
        """The pill itself -- shadow, glass body, dome, rim. Supersampled."""
        key = (self.canvas_w, self.canvas_h)
        cached = self._shell_cache.get(key)
        if cached is not None:
            return cached.copy()

        from PIL import Image, ImageDraw, ImageFilter

        s = SS
        w, h = self.canvas_w * s, self.canvas_h * s
        pad, rad = self.pad * s, self.radius * s
        pill = (pad, pad, pad + self.width * s, pad + self.height * s)

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        # 1. Contact shadow: a blurred, slightly offset copy of the pill.
        #    Drawn on its own layer so the blur cannot bleed into the glass.
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        offset = int(round(3 * self.scale * s))
        self._rounded(
            sdraw,
            (pill[0], pill[1] + offset, pill[2], pill[3] + offset),
            rad, SHADOW,
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(1.0, 5.0 * self.scale * s / 2)))
        img.alpha_composite(shadow)

        # 2. Glass body.
        body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(body)
        self._rounded(bdraw, pill, rad, GLASS_FILL)

        # 3. Convex dome: a vertical white gradient, clipped to the pill. This
        #    is what gives the droplet its curvature -- brightest at the top,
        #    gone by mid-height, with a faint bounce at the very bottom.
        grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(grad)
        top, bottom = pill[1], pill[3]
        span = max(1, bottom - top)
        for y in range(top, bottom):
            t = (y - top) / span
            if t < 0.5:
                colour = _lerp_rgba(GLASS_TOP, (255, 255, 255, 0), t / 0.5)
            else:
                colour = _lerp_rgba((255, 255, 255, 0), GLASS_BOTTOM, (t - 0.5) / 0.5)
            gdraw.line((pill[0], y, pill[2], y), fill=colour)
        mask = Image.new("L", (w, h), 0)
        self._rounded(ImageDraw.Draw(mask), pill, rad, 255)
        body.alpha_composite(Image.composite(grad, Image.new("RGBA", (w, h), (0, 0, 0, 0)), mask))

        # 4. Specular streak just under the top edge.
        cx = (pill[0] + pill[2]) / 2
        streak_w = (pill[2] - pill[0]) * 0.42
        sy = pill[1] + rad * 0.30
        streak, sdraw2 = self._layer((w, h))
        sdraw2.line(
            (cx - streak_w / 2, sy, cx + streak_w / 2, sy),
            fill=STREAK, width=max(1, int(round(1.2 * self.scale * s))),
        )
        body.alpha_composite(streak)

        # 5. Rim. A real glass edge catches the light along its top and only
        #    hints at it underneath, so the bright rim is drawn as a full
        #    outline and then faded out towards the bottom with a mask. (Not
        #    `arc()`: on a 200x48 box that draws one enormous ellipse, not the
        #    outline of the pill.)
        rim_w = max(1, int(round(1.1 * self.scale * s)))
        rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self._rounded(ImageDraw.Draw(rim), pill, rad, None, outline=RIM_BOTTOM, width=rim_w)
        body.alpha_composite(rim)

        rim_lit = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self._rounded(ImageDraw.Draw(rim_lit), pill, rad, None, outline=RIM_TOP, width=rim_w)
        ramp = Image.new("L", (w, h), 0)
        rdraw = ImageDraw.Draw(ramp)
        for y in range(top, bottom):
            t = (y - top) / span
            rdraw.line((0, y, w, y), fill=int(255 * max(0.0, 1.0 - (t / 0.62) ** 1.6)))
        rim_lit.putalpha(Image.composite(rim_lit.getchannel("A"), Image.new("L", (w, h), 0), ramp))
        body.alpha_composite(rim_lit)

        img.alpha_composite(body)
        self._shell_cache[key] = img
        return img.copy()

    # -- one animation frame ----------------------------------------------
    def frame(self, state: str, label: str, phase: float, level: float,
              bar_vals: list[float], translate: bool = False) -> "object":
        """Full RGBA frame at final resolution."""
        from PIL import Image, ImageDraw

        s = SS
        img = self.shell()
        # Every dynamic element lands on this layer, composited once at the
        # end -- see _layer() for why they cannot be drawn onto the glass.
        overlay, draw = self._layer(img.size)
        pad = self.pad * s
        cy = pad + (self.height * s) / 2.0

        # Bead: the state indicator, a lit droplet of glass.
        bead_cx = pad + 22 * self.scale * s
        if state == "transcribing":
            orbit = 2.0 * self.scale * s
            bx = bead_cx + orbit * math.cos(phase * 1.8)
            by = cy + orbit * math.sin(phase * 1.8)
            core_r = 3.2 * self.scale * s
            halo_r = core_r + 2.8 * self.scale * s
        elif state in ("done", "preview"):
            bx, by = bead_cx, cy
            core_r = 4.2 * self.scale * s
            halo_r = 7.0 * self.scale * s
        else:
            bx, by = bead_cx, cy
            breath = 0.5 + 0.5 * math.sin(phase * 1.4)
            core_r = (3.5 + 1.0 * breath + level * 1.2) * self.scale * s
            halo_r = core_r + (2.5 + level * 3.0) * self.scale * s

        draw.ellipse((bx - halo_r, by - halo_r, bx + halo_r, by + halo_r), fill=BEAD_HALO)
        draw.ellipse((bx - core_r, by - core_r, bx + core_r, by + core_r), fill=BEAD_CORE)
        spec_r = core_r * 0.28
        sx, sy = bx - core_r * 0.45, by - core_r * 0.45
        draw.ellipse((sx - spec_r, sy - spec_r, sx + spec_r, sy + spec_r), fill=BEAD_SPEC)

        # Wave bars, right-aligned inside the pill.
        right = pad + self.width * s
        total = (BAR_COUNT - 1) * BAR_GAP * self.scale * s
        base_x = right - 16 * self.scale * s - total
        head = (phase * 0.75) % (BAR_COUNT + 2) - 1
        bar_w = BAR_W * self.scale * s
        for i in range(BAR_COUNT):
            bx_i = base_x + i * BAR_GAP * self.scale * s
            half_h = max(bar_w / 2.0, bar_vals[i] * self.scale * s)
            if state == "transcribing":
                crest = max(0.0, 1.0 - abs(i - head) / 1.5)
                colour = _lerp_rgba(BAR_DIM, BAR_LIVE, crest)
            elif state == "preview":
                colour = BAR_DIM
            else:
                colour = BAR_LIVE
            self._rounded(
                draw,
                (bx_i - bar_w / 2, cy - half_h, bx_i + bar_w / 2, cy + half_h),
                bar_w / 2, colour,
            )

        # Label, between the bead and the bars.
        if label:
            colour = {
                "listening": TEXT_LIVE, "transcribing": TEXT_SPIN,
                "preview": TEXT_PREVIEW, "done": TEXT_DONE,
            }.get(state, TEXT_LIVE)
            font = self.font(12.5)
            text_x = pad + 38 * self.scale * s
            text_right = base_x - 8 * self.scale * s
            draw.text((text_x, cy), self._fit(label, font, text_right - text_x),
                      font=font, fill=colour, anchor="lm")

        # Translation badge: monochrome by design -- the palette is
        # achromatic, so the mode is signalled by a mark, never by a hue.
        if translate:
            font = self.font(8.0)
            draw.text((right - 8 * self.scale * s, pad + 9 * self.scale * s),
                      "FR→EN", font=font, fill=(255, 255, 255, 150), anchor="rm")

        img.alpha_composite(overlay)
        return img.resize((self.canvas_w, self.canvas_h), Image.LANCZOS)

    def _fit(self, text: str, font, max_px: float) -> str:
        """Ellipsize from the *left*: for live text the newest words matter."""
        from PIL import Image, ImageDraw

        draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        def width(value: str) -> float:
            try:
                box = draw.textbbox((0, 0), value, font=font)
                return box[2] - box[0]
            except Exception:
                return len(value) * 6.0

        if max_px <= 0 or width(text) <= max_px:
            return text
        trimmed = text
        while trimmed and width("…" + trimmed) > max_px:
            trimmed = trimmed[1:]
        return "…" + trimmed if trimmed else ""


# --- Windows layered-window blitting ----------------------------------------
class _LayeredWindow:
    """Pushes an RGBA image onto an HWND with per-pixel alpha."""

    def __init__(self, hwnd: int) -> None:
        import ctypes
        from ctypes import wintypes

        self.hwnd = hwnd
        self._ctypes = ctypes
        self._wintypes = wintypes
        self.user32 = ctypes.windll.user32          # type: ignore[attr-defined]
        self.gdi32 = ctypes.windll.gdi32            # type: ignore[attr-defined]
        self._dib = None
        self._dib_size = (0, 0)
        self._bits = None
        self._memdc = None

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        get_l = getattr(self.user32, "GetWindowLongPtrW", self.user32.GetWindowLongW)
        set_l = getattr(self.user32, "SetWindowLongPtrW", self.user32.SetWindowLongW)
        get_l.argtypes = [wintypes.HWND, ctypes.c_int]
        get_l.restype = ctypes.c_void_p
        set_l.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        set_l.restype = ctypes.c_void_p
        style = get_l(wintypes.HWND(hwnd), GWL_EXSTYLE) or 0
        set_l(wintypes.HWND(hwnd), GWL_EXSTYLE, ctypes.c_void_p(int(style) | WS_EX_LAYERED))

    def _ensure_dib(self, width: int, height: int):
        ctypes = self._ctypes
        if self._dib is not None and self._dib_size == (width, height):
            return
        self._release_dib()

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        # Negative height = top-down DIB, matching Pillow's row order. With a
        # positive height the bubble comes out mirrored vertically.
        header.biHeight = -height
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB

        bits = ctypes.c_void_p()
        screen_dc = self.user32.GetDC(None)
        try:
            self._memdc = self.gdi32.CreateCompatibleDC(screen_dc)
            self._dib = self.gdi32.CreateDIBSection(
                screen_dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0
            )
        finally:
            self.user32.ReleaseDC(None, screen_dc)
        if not self._dib:
            raise RuntimeError("CreateDIBSection failed")
        self.gdi32.SelectObject(self._memdc, self._dib)
        self._bits = bits
        self._dib_size = (width, height)

    def _release_dib(self) -> None:
        try:
            if self._dib:
                self.gdi32.DeleteObject(self._dib)
            if self._memdc:
                self.gdi32.DeleteDC(self._memdc)
        except Exception:
            pass
        self._dib = None
        self._memdc = None
        self._bits = None
        self._dib_size = (0, 0)

    def blit(self, image, x: int, y: int, alpha: float = 1.0) -> None:
        """Show `image` (RGBA) at screen position (x, y)."""
        import numpy as np

        ctypes = self._ctypes
        wintypes = self._wintypes
        width, height = image.size
        self._ensure_dib(width, height)

        # UpdateLayeredWindow wants premultiplied BGRA. Skipping the
        # premultiplication is what produces the classic milky halo around
        # translucent edges.
        arr = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        a = arr[:, :, 3].astype(np.uint16)
        rgb = (arr[:, :, :3].astype(np.uint16) * a[:, :, None] // 255).astype(np.uint8)
        bgra = np.dstack((rgb[:, :, ::-1], arr[:, :, 3])).copy(order="C")
        ctypes.memmove(self._bits, bgra.ctypes.data, bgra.nbytes)

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class SIZE(ctypes.Structure):
            _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                        ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]

        blend = BLENDFUNCTION(0, 0, max(0, min(255, int(round(alpha * 255)))), 1)  # AC_SRC_ALPHA
        src = POINT(0, 0)
        dst = POINT(int(x), int(y))
        size = SIZE(width, height)

        screen_dc = self.user32.GetDC(None)
        try:
            ok = self.user32.UpdateLayeredWindow(
                wintypes.HWND(self.hwnd), screen_dc, ctypes.byref(dst), ctypes.byref(size),
                self._memdc, ctypes.byref(src), 0, ctypes.byref(blend), 2,  # ULW_ALPHA
            )
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.user32.ReleaseDC(None, screen_dc)

    def close(self) -> None:
        self._release_dib()


def _window_handle(win) -> int:
    """Top-level HWND of a Tk window."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetAncestor.restype = wintypes.HWND
    raw = win.winfo_id()
    return int(user32.GetAncestor(wintypes.HWND(raw), 2) or raw)  # GA_ROOT


def _no_activate(hwnd: int) -> None:
    """Ask Windows never to activate this window (the paste must land elsewhere)."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
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
    """A translucent glass pill showing dictation state.

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
        self._dead = False
        self._stopping = False

        # Tk-thread-only state.
        self._tk = None
        self._root = None
        self._win = None
        self._layered: _LayeredWindow | None = None
        self._renderer: GlassRenderer | None = None
        self._scale = 1.0

        self._state = "hidden"
        self._label = ""
        self._translate = False
        self._visible = False
        self._phase = 0.0
        self._anim_id = None
        self._hide_id = None
        self._alpha = 1.0
        self._bar_vals: list[float] = [BAR_W / 2.0] * BAR_COUNT
        self._xy = (0, 0)
        self._pill_w = BUBBLE_W
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
                from PIL import Image  # noqa: F401
            except Exception as exc:
                self._dead = True
                debug_log(f"bubble: tkinter/Pillow unavailable ({exc!r}); bubble disabled")
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
            try:
                self._scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
            except Exception:
                self._scale = 1.0
            self._renderer = GlassRenderer(scale=self._scale)
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

    def set_text(self, text: str) -> None:
        """Update the label only -- used by the live transcript preview."""
        self._post(lambda: self._do_set_text(text))

    def set_translate(self, on: bool) -> None:
        self._post(lambda: self._do_set_translate(bool(on)))

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
        # No -alpha and no -transparentcolor: both go through
        # SetLayeredWindowAttributes, which is mutually exclusive with the
        # UpdateLayeredWindow path used for per-pixel alpha.
        win.geometry(f"{self._renderer.canvas_w}x{self._renderer.canvas_h}+0+0")
        win.update_idletasks()

        try:
            hwnd = _window_handle(win)
            _no_activate(hwnd)
            self._layered = _LayeredWindow(hwnd)
        except Exception as exc:
            debug_log(f"bubble: layered window unavailable ({exc!r}); bubble disabled")
            self._dead = True
            return False

        win.bind("<Button-1>", self._on_press)
        win.bind("<B1-Motion>", self._on_drag)
        win.bind("<ButtonRelease-1>", self._on_release)
        return True

    # --- Tk thread: placement ------------------------------------------------
    def _resize_for(self, label: str) -> None:
        """Grow the pill so `label` fits, within PREVIEW_W_MAX."""
        renderer = self._renderer
        if renderer is None:
            return
        needed = 38 + renderer.text_width(label) + 10 + (BAR_COUNT - 1) * BAR_GAP + 16 + 10
        target = int(max(BUBBLE_W, min(PREVIEW_W_MAX, needed)))
        if target == self._pill_w:
            return
        self._pill_w = target
        self._renderer = GlassRenderer(width=target, scale=self._scale)
        # Keep the renderer's font/shell caches warm across resizes only when
        # the size is unchanged; a new width needs a new shell anyway.
        if self._win is not None:
            try:
                self._win.geometry(f"{self._renderer.canvas_w}x{self._renderer.canvas_h}")
            except Exception:
                pass

    def _place(self) -> None:
        renderer = self._renderer
        sw = int(self._root.winfo_screenwidth())
        sh = int(self._root.winfo_screenheight())
        left, top, right, bottom = _work_area(sw, sh)
        cw, ch = renderer.canvas_w, renderer.canvas_h

        if self.pos is not None:
            # Stored position is the pill's top-left; the canvas is padded.
            x = int(self.pos[0]) - renderer.pad
            y = int(self.pos[1]) - renderer.pad
        else:
            x = left + (right - left - cw) // 2
            margin = int(MARGIN * self._scale)
            y = top + margin if self.position == "top" else bottom - ch - margin

        vleft, vtop, vright, vbottom = _virtual_screen(sw, sh)
        x = max(vleft, min(x, vright - cw))
        y = max(vtop, min(y, vbottom - ch))
        self._xy = (x, y)

    # --- Tk thread: commands -------------------------------------------------
    def _do_show(self, state: str, text: str) -> None:
        if not self._ensure_win():
            return
        self._cancel_hide()
        self._alpha = 1.0
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
        if state not in _STATES:
            state = "listening"
        self._state = state
        if text:
            self._do_set_text(text)

    def _do_set_text(self, text: str) -> None:
        text = str(text or "")
        if text == self._label:
            return
        self._label = text
        self._resize_for(text)
        if self._visible:
            self._place()

    def _do_set_translate(self, on: bool) -> None:
        self._translate = on

    def _do_flash_done(self, text: str, ms: int) -> None:
        if self._win is None:
            self._do_show("done", text or "Collé")
        else:
            self._cancel_hide()
            self._do_set_state("done", text or "Collé")
            if not self._visible:
                self._place()
                self._alpha = 1.0
                try:
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
        self._label = ""
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
        if self._layered is not None:
            try:
                self._layered.close()
            except Exception:
                pass
            self._layered = None
        for obj in (self._win, self._root):
            try:
                if obj is not None:
                    obj.destroy()
            except Exception:
                pass
        self._win = None
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
            self._xy = (event.x_root - self._drag[0], event.y_root - self._drag[1])
            self._drag_moved = True
            self._render()
        except Exception:
            pass

    def _on_release(self, event) -> None:
        moved = self._drag_moved
        self._drag = None
        self._drag_moved = False
        if not moved or self._renderer is None:
            return
        # Report the *pill* corner, not the padded canvas corner, so a stored
        # position means the same thing whatever the shadow padding is.
        x = int(self._xy[0]) + self._renderer.pad
        y = int(self._xy[1]) + self._renderer.pad
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
            center_idx = (BAR_COUNT - 1) / 2.0
            for i in range(BAR_COUNT):
                ripple_phase = self._phase * 1.3 + (i - center_idx) * 0.55
                wave_shimmer = 0.50 + 0.50 * math.sin(ripple_phase)
                idle_breath = 1.1 + 0.8 * (0.5 + 0.5 * math.sin(self._phase * 0.7 + i * 0.4))
                dist = abs(i - center_idx) / center_idx
                center_weight = 1.0 - 0.28 * (dist ** 2)
                out.append(floor + idle_breath + level * BAR_MAX * wave_shimmer * center_weight)
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

        if self._state == "preview":
            return [floor + 0.8] * BAR_COUNT

        return [floor] * BAR_COUNT

    def _render(self) -> None:
        if self._layered is None or self._renderer is None:
            return
        image = self._renderer.frame(
            self._state, self._label, self._phase, self._level,
            self._bar_vals, self._translate,
        )
        self._layered.blit(image, self._xy[0], self._xy[1], self._alpha)

    def _tick(self) -> None:
        self._anim_id = None
        if not self._visible:
            return
        self._phase += 0.12 * (FRAME_MS / 12.0)

        try:
            targets = self._targets()
            for i, target in enumerate(targets):
                ease = EASE_UP if target > self._bar_vals[i] else EASE_DOWN
                self._bar_vals[i] += (target - self._bar_vals[i]) * ease
            self._render()
        except Exception as exc:
            debug_log(f"bubble: animation stopped ({exc!r})")
            return

        try:
            self._anim_id = self._root.after(FRAME_MS, self._tick)
        except Exception:
            self._anim_id = None

    def _fade_out(self) -> None:
        self._hide_id = None
        self._alpha -= 0.12
        if self._alpha <= 0.04 or self._win is None:
            self._do_hide()
            return
        try:
            self._render()
        except Exception:
            self._do_hide()
            return
        try:
            self._hide_id = self._root.after(FRAME_MS, self._fade_out)
        except Exception:
            self._do_hide()
