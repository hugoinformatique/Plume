"""Central design tokens and the shared Plume icon.

Keeping colors, fonts and the app mark in one place so the window, the tray
icon and the floating listening bubble all read as one product. PIL is imported
lazily inside the icon helper so importing this module never requires Pillow.
"""

from __future__ import annotations

from pathlib import Path


# --- Palette -----------------------------------------------------------------
BRAND = "#0F1115"        # monochrome app icon background
BRAND_DARK = "#000000"
INK = "#12141C"          # near-black surface (bubble / dark UI)
INK_SOFT = "#1B1E29"
SURFACE = "#F6F7FB"      # light window background
CARD = "#FFFFFF"
TEXT = "#E9EBF5"         # light text on dark
TEXT_DARK = "#1C1F2A"    # dark text on light
MUTED = "#9AA0B4"
ACCENT = "#22D3A6"       # "listening" / active accent (teal-green)
DANGER = "#FF6B6B"
BORDER = "#E2E5EF"

FONT_UI = "Segoe UI"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(color_a: str, color_b: str, t: float) -> str:
    """Blend two hex colors. t=0 -> color_a, t=1 -> color_b."""
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    r = tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))
    return "#%02X%02X%02X" % r


def _feather_layer(size: int, fg: str, spine: str):
    """Draw a stylised feather (vane + spine + barbs) on a transparent layer."""
    from PIL import Image, ImageDraw

    s = size * 3  # supersample for smooth edges
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    cx = s // 2
    top = int(s * 0.15)
    bot = int(s * 0.87)
    half = int(s * 0.16)

    # Vane: a tall leaf.
    d.ellipse((cx - half, top, cx + half, bot), fill=fg)

    # Barbs: subtle diagonal separators, drawn in the spine colour.
    n = 8
    barb_w = max(1, int(s * 0.006))
    for i in range(1, n):
        y = top + (bot - top) * i // n
        d.line((cx, y, cx - half, y - int(s * 0.035)), fill=spine, width=barb_w)
        d.line((cx, y, cx + half, y - int(s * 0.035)), fill=spine, width=barb_w)

    # Spine on top.
    d.line((cx, top + int(s * 0.03), cx, bot - int(s * 0.02)), fill=spine, width=max(2, int(s * 0.014)))

    layer = layer.rotate(35, resample=Image.BICUBIC, expand=False)
    return layer.resize((size, size), Image.LANCZOS)


def make_icon_image(size: int = 64, bg: str = BRAND, fg: str = "#FFFFFF"):
    """Return an RGBA PIL image: a monochrome rounded tile with a feather."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = max(4, int(size * 0.22))
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=bg)
    img.alpha_composite(_feather_layer(size, fg=fg, spine=bg))
    return img


def _vertical_gradient(size: tuple[int, int], top: str, bottom: str):
    """A smooth top-to-bottom blend, as an RGB image."""
    from PIL import Image

    width, height = size
    column = Image.new("RGB", (1, height))
    for y in range(height):
        column.putpixel((0, y), _hex_to_rgb(mix(top, bottom, y / max(1, height - 1))))
    return column.resize((width, height), Image.BICUBIC)


def make_wizard_image(width: int = 164, height: int = 314):
    """Large artwork for the installer's welcome/finish pages.

    Inno Setup wants a bitmap, and it does not composite alpha, so this is
    rendered flat on the brand gradient rather than handed a transparent icon.
    Same feather mark as the app, so the setup wizard and the app read as one
    product instead of a generic blue Inno window.
    """
    from PIL import Image

    img = _vertical_gradient((width, height), BRAND_DARK, mix(BRAND, SURFACE, 0.10))

    # Oversized feather bleeding off the bottom-right corner. Drawn in white
    # and then taken down to ~9% alpha: a watermark has to sit *under* the
    # wizard text, so it is defined by the faint edge of its shape, not by its
    # internal lines -- hence the near-identical vane and spine colours.
    mark_size = int(width * 1.9)
    mark = _feather_layer(mark_size, fg="#FFFFFF", spine="#E8E8E8")
    faint = mark.copy()
    faint.putalpha(mark.getchannel("A").point(lambda a: int(a * 0.09)))
    img.paste(faint.convert("RGB"), (int(width * 0.30), int(height * 0.42)), faint)

    # A single hairline down the right edge, where the bitmap meets the white
    # wizard page: without it the artwork ends on a soft gradient and looks
    # unfinished against the panel.
    from PIL import ImageDraw

    ImageDraw.Draw(img).line(
        (width - 1, 0, width - 1, height), fill=_hex_to_rgb(mix(BRAND, "#FFFFFF", 0.18)), width=1
    )

    # The crisp app mark, upper area, where the eye lands first.
    icon_size = int(width * 0.34)
    icon = make_icon_image(icon_size)
    img.paste(icon.convert("RGB"), (int(width * 0.17), int(height * 0.13)), icon)
    return img


def make_wizard_small_image(size: int = 55):
    """The little header image shown on every page after the welcome one."""
    from PIL import Image

    img = _vertical_gradient((size, size), BRAND_DARK, BRAND)
    icon = make_icon_image(size)
    img.paste(icon.convert("RGB"), (0, 0), icon)
    return img


def save_icon_assets(assets_dir: Path) -> tuple[Path, ...]:
    """Write the icon and the Inno Setup wizard bitmaps into `assets_dir`.

    Returns every path written, in the order they are produced.
    """
    assets_dir.mkdir(parents=True, exist_ok=True)
    png_path = assets_dir / "plume.png"
    ico_path = assets_dir / "plume.ico"

    make_icon_image(256).save(png_path)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    make_icon_image(256).save(ico_path, sizes=[(s, s) for s in sizes])

    written = [png_path, ico_path]
    # Inno picks the best size from the comma-separated list in Plume.iss, so
    # ship the scaled variants too -- otherwise the wizard upscales a 164px
    # bitmap on a HiDPI laptop and the setup looks cheap next to the app.
    for scale, suffix in ((1, ""), (2, "-2x"), (3, "-3x")):
        big = assets_dir / f"wizard{suffix}.bmp"
        small = assets_dir / f"wizard-small{suffix}.bmp"
        make_wizard_image(164 * scale, 314 * scale).save(big)
        make_wizard_small_image(55 * scale).save(small)
        written += [big, small]
    return tuple(written)
