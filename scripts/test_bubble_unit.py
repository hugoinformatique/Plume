import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestFloatingBubbleLogic(unittest.TestCase):
    def test_geometry_points(self):
        from floating_bubble import _rr_points, _capsule_points, _specular_crescent_points, BUBBLE_W, BUBBLE_H, RADIUS

        pts = _rr_points(2, 2, BUBBLE_W - 2, BUBBLE_H - 3, RADIUS)
        self.assertEqual(len(pts), 24)
        for i in range(0, len(pts), 2):
            x, y = pts[i], pts[i+1]
            self.assertTrue(2 <= x <= BUBBLE_W - 2)
            self.assertTrue(2 <= y <= BUBBLE_H - 3)

        caps = _capsule_points(100, 34, 15, 6)
        self.assertEqual(len(caps), 24)

        cresc = _specular_crescent_points(BUBBLE_W, BUBBLE_H, RADIUS)
        self.assertTrue(len(cresc) >= 12)

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

    def test_targets_listening(self):
        from floating_bubble import FloatingBubble, BAR_COUNT, BAR_W
        bubble = FloatingBubble()
        bubble._state = "listening"
        bubble._level = 0.8
        bubble._phase = 1.0
        targets = bubble._targets()
        self.assertEqual(len(targets), BAR_COUNT)
        for t in targets:
            self.assertGreaterEqual(t, BAR_W / 2.0)

    def test_targets_transcribing(self):
        from floating_bubble import FloatingBubble, BAR_COUNT, BAR_W
        bubble = FloatingBubble()
        bubble._state = "transcribing"
        bubble._phase = 2.5
        targets = bubble._targets()
        self.assertEqual(len(targets), BAR_COUNT)
        for t in targets:
            self.assertGreaterEqual(t, BAR_W / 2.0)

    def test_targets_done(self):
        from floating_bubble import FloatingBubble, BAR_COUNT, BAR_W
        bubble = FloatingBubble()
        bubble._state = "done"
        targets = bubble._targets()
        self.assertEqual(len(targets), BAR_COUNT)
        for t in targets:
            self.assertGreaterEqual(t, BAR_W / 2.0)

if __name__ == "__main__":
    unittest.main()
