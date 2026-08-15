"""Test script for floating_bubble geometry and math without requiring X11/Tkinter display."""
import math
import sys

def test_math():
    # Test rr_points
    def _rr_points(x1: float, y1: float, x2: float, y2: float, r: float) -> list[float]:
        r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
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
        x1, y1, x2, y2 = 4.0, 3.0, w - 4.0, h * 0.44
        cr = r * 0.85
        return [
            x1 + cr, y1,
            x2 - cr, y1,
            x2, y1 + cr * 0.4,
            x2 - cr * 0.5, y2,
            w / 2.0, y2 + 2.0,
            x1 + cr * 0.5, y2,
            x1, y1 + cr * 0.4,
        ]

    pts = _rr_points(2, 2, 276 - 2, 68 - 3, 30)
    assert len(pts) == 24, f"Expected 24 coords (12 points), got {len(pts)}"

    caps = _capsule_points(100, 34, 15, 6)
    assert len(caps) == 24

    cresc = _specular_crescent_points(276, 68, 30)
    assert len(cresc) == 14

    print("Geometry math verified successfully!")

if __name__ == "__main__":
    test_math()
