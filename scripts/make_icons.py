"""Generate the Plume icon assets (assets/plume.png and assets/plume.ico).

Run before packaging so the installer/exe carry the feather icon:

    python scripts/make_icons.py

Requires Pillow (already in requirements.txt).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from repo root or from scripts/.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui_theme import save_icon_assets  # noqa: E402


def main() -> int:
    for path in save_icon_assets(ROOT / "assets"):
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
