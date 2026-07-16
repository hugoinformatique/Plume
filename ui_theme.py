"""Central design tokens and the shared Plume icon.

Keeping colors, fonts and the app mark in one place so the window, the tray
icon and the floating listening bubble all read as one product. PIL is imported
lazily inside the icon helper so importing this module never requires Pillow.
"""

from __future__ import annotations

from pathlib import Path


# --- Palette -----------------------------------------------------------------
BRAND = "#5B6EF5"        # primary indigo
BRAND_DARK = "#3E4BD8"
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
    """Return an RGBA PIL image: a rounded brand tile with a white feather."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = max(4, int(size * 0.22))
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=bg)
    img.alpha_composite(_feather_layer(size, fg=fg, spine=bg))
    return img


def save_icon_assets(assets_dir: Path) -> tuple[Path, Path]:
    """Write assets/plume.png (256) and assets/plume.ico (multi-size)."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    png_path = assets_dir / "plume.png"
    ico_path = assets_dir / "plume.ico"

    make_icon_image(256).save(png_path)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    make_icon_image(256).save(ico_path, sizes=[(s, s) for s in sizes])
    return png_path, ico_path
