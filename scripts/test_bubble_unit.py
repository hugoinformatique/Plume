"""Unit tests for the floating bubble: glass rendering and animation state.

No display and no Windows API needed -- `GlassRenderer` is deliberately pure,
and the `FloatingBubble` logic exercised here never touches Tk.

    python scripts/test_bubble_unit.py

Needs Pillow and numpy (both already in requirements.txt).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGlassRenderer(unittest.TestCase):
    def setUp(self):
        from floating_bubble import GlassRenderer

        self.renderer = GlassRenderer(scale=1.0)
        self.bars = [4.0, 8.0, 12.0, 7.0, 5.0]

    def frame(self, state="listening", label="À l'écoute…", translate=False):
        return self.renderer.frame(state, label, 1.0, 0.5, self.bars, translate)

    def test_frame_size_matches_window(self):
        frame = self.frame()
        self.assertEqual(frame.size, (self.renderer.canvas_w, self.renderer.canvas_h))
        self.assertEqual(frame.mode, "RGBA")

    def test_corners_are_fully_transparent(self):
        """The padding around the pill must be empty, or the window shows as a box."""
        frame = self.frame()
        w, h = frame.size
        for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            self.assertEqual(frame.getpixel(xy)[3], 0, f"corner {xy} is not transparent")

    def test_body_is_translucent_not_opaque(self):
        """The whole point of the rewrite: the desktop must show through."""
        frame = self.frame(label="")
        # A point inside the pill, away from the bead, the bars and the text.
        x = self.renderer.pad + int(self.renderer.width * 0.62)
        y = self.renderer.pad + int(self.renderer.height * 0.78)
        alpha = frame.getpixel((x, y))[3]
        self.assertGreater(alpha, 40, "glass is too faint to read as a surface")
        self.assertLess(alpha, 235, "glass is opaque -- that is the black-pebble bug")

    def test_rounded_edge_is_antialiased(self):
        """Intermediate alphas along the curve are what "not pixelated" means."""
        frame = self.frame(label="")
        pad, h = self.renderer.pad, self.renderer.height
        y = pad + h // 2
        alphas = [frame.getpixel((x, y))[3] for x in range(0, pad + 12)]
        partial = [a for a in alphas if 12 < a < 243]
        self.assertGreaterEqual(
            len(partial), 2, f"hard 1-bit edge, no antialiasing: {alphas}"
        )

    def test_bead_is_solid_not_a_ring(self):
        """A translucent halo drawn straight onto the glass punched a hole
        through it, and the bead came out as a ring. Guard against it."""
        frame = self.frame(label="")
        cx = self.renderer.pad + int(22 * self.renderer.scale)
        cy = self.renderer.pad + self.renderer.height // 2
        self.assertGreater(frame.getpixel((cx, cy))[3], 240)

    def test_pill_grows_with_text(self):
        from floating_bubble import BUBBLE_W, PREVIEW_W_MAX, GlassRenderer

        short = self.renderer.text_width("Collé")
        long = self.renderer.text_width("Bonjour Marc, je te confirme le rendez-vous de mardi.")
        self.assertGreater(long, short)
        wide = GlassRenderer(width=min(PREVIEW_W_MAX, int(BUBBLE_W + long)), scale=1.0)
        self.assertGreater(wide.canvas_w, self.renderer.canvas_w)

    def test_long_label_is_ellipsized_from_the_left(self):
        """The end of the sentence is the part worth keeping on screen."""
        font = self.renderer.font(12.5)
        fitted = self.renderer._fit("un deux trois quatre cinq six sept huit", font, 60)
        self.assertTrue(fitted.startswith("…"), fitted)
        self.assertTrue(fitted.endswith("huit"), fitted)

    def test_translate_badge_changes_the_frame(self):
        plain = self.frame(translate=False).tobytes()
        badged = self.frame(translate=True).tobytes()
        self.assertNotEqual(plain, badged)

    def test_states_render_differently(self):
        seen = {state: self.frame(state=state, label="x").tobytes()
                for state in ("listening", "transcribing", "preview", "done")}
        self.assertEqual(len(set(seen.values())), 4)


class TestPremultipliedAlpha(unittest.TestCase):
    """UpdateLayeredWindow takes premultiplied BGRA; getting this wrong shows
    up as a milky halo around every translucent edge."""

    def test_premultiplication_matches_the_blit_path(self):
        import numpy as np
        from PIL import Image

        image = Image.new("RGBA", (2, 1), (255, 255, 255, 0))
        image.putpixel((0, 0), (255, 128, 0, 128))
        image.putpixel((1, 0), (255, 255, 255, 0))

        arr = np.asarray(image, dtype=np.uint8)
        a = arr[:, :, 3].astype(np.uint16)
        rgb = (arr[:, :, :3].astype(np.uint16) * a[:, :, None] // 255).astype(np.uint8)
        bgra = np.dstack((rgb[:, :, ::-1], arr[:, :, 3]))

        self.assertEqual(list(bgra[0, 0]), [0, 64, 128, 128])   # B, G, R, A
        self.assertEqual(list(bgra[0, 1]), [0, 0, 0, 0])        # fully transparent


class TestBubbleLogic(unittest.TestCase):
    def test_level_clamping(self):
        from floating_bubble import FloatingBubble

        bubble = FloatingBubble()
        bubble.set_level(0.5)
        self.assertAlmostEqual(bubble._level, 0.5)
        bubble.set_level(-1.0)
        self.assertAlmostEqual(bubble._level, 0.0)
        bubble.set_level(2.5)
        self.assertAlmostEqual(bubble._level, 1.0)
        bubble.set_level("invalid")
        self.assertAlmostEqual(bubble._level, 0.0)

    def test_targets_per_state(self):
        from floating_bubble import FloatingBubble, BAR_COUNT, BAR_W

        bubble = FloatingBubble()
        floor = BAR_W / 2.0

        bubble._state, bubble._level = "listening", 1.0
        loud = bubble._targets()
        bubble._level = 0.0
        quiet = bubble._targets()
        self.assertEqual(len(loud), BAR_COUNT)
        self.assertGreater(max(loud), max(quiet), "bars must react to the voice")
        self.assertTrue(all(value >= floor for value in quiet))

        bubble._state = "transcribing"
        self.assertEqual(len(bubble._targets()), BAR_COUNT)

        bubble._state = "hidden"
        self.assertEqual(bubble._targets(), [floor] * BAR_COUNT)

    def test_public_api_is_safe_without_a_display(self):
        """Every entry point must be a no-op rather than an exception when the
        window cannot exist -- a decoration must never take dictation down."""
        from floating_bubble import FloatingBubble

        bubble = FloatingBubble()
        bubble._dead = True
        bubble.show()
        bubble.set_state("transcribing", "…")
        bubble.set_text("hello")
        bubble.set_translate(True)
        bubble.flash_done("Collé")
        bubble.hide()
        bubble.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
