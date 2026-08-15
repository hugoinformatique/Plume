"""Mock Tkinter tests for FloatingBubble rendering and lifecycle."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from floating_bubble import FloatingBubble, BUBBLE_W, BUBBLE_H

class DummyEvent:
    def __init__(self, x, y, x_root=0, y_root=0):
        self.x = x
        self.y = y
        self.x_root = x_root
        self.y_root = y_root

class TestFloatingBubbleWithMockTk(unittest.TestCase):
    def setUp(self):
        self.bubble = FloatingBubble()
        self.mock_tk = MagicMock()
        self.mock_root = MagicMock()
        self.mock_win = MagicMock()
        self.mock_canvas = MagicMock()

        self.mock_root.winfo_screenwidth.return_value = 1920
        self.mock_root.winfo_screenheight.return_value = 1080
        self.mock_tk.Toplevel.return_value = self.mock_win
        self.mock_tk.Canvas.return_value = self.mock_canvas

        self.bubble._tk = self.mock_tk
        self.bubble._root = self.mock_root
        self.bubble._ensure_win()

    def test_ensure_win_and_build(self):
        # Reset win and mock so ensure_win runs
        self.bubble._win = None
        self.mock_tk.reset_mock()
        self.mock_canvas.reset_mock()
        ok = self.bubble._ensure_win()
        self.assertTrue(ok)
        self.mock_tk.Toplevel.assert_called_once_with(self.mock_root)
        self.mock_canvas.pack.assert_called_once()
        self.assertEqual(len(self.bubble._bars), 5)
        self.assertIsNotNone(self.bubble._dot)
        self.assertIsNotNone(self.bubble._dot_halo)
        self.assertIsNotNone(self.bubble._dot_spec)
        self.assertIsNotNone(self.bubble._label)

    def test_placement_bottom_and_top(self):
        self.bubble._place()
        self.mock_win.geometry.assert_called()

        self.bubble.position = "top"
        self.bubble._place()
        self.mock_win.geometry.assert_called()

        self.bubble.pos = (500, 600)
        self.bubble._place()
        self.mock_win.geometry.assert_called_with(f"{BUBBLE_W}x{BUBBLE_H}+500+600")

    def test_show_and_states(self):
        self.bubble._do_show("listening", "À l'écoute…")
        self.assertTrue(self.bubble._visible)
        self.assertEqual(self.bubble._state, "listening")
        self.mock_canvas.itemconfigure.assert_called()

        self.bubble._do_set_state("transcribing", "Transcription…")
        self.assertEqual(self.bubble._state, "transcribing")

        self.bubble._do_set_state("done", "Collé")
        self.assertEqual(self.bubble._state, "done")

    def test_tick_animation(self):
        self.bubble._visible = True
        self.bubble._state = "listening"
        self.bubble._level = 0.6
        self.bubble._tick()
        self.mock_canvas.coords.assert_called()
        self.mock_root.after.assert_called()

    def test_tick_transcribing_animation(self):
        self.bubble._visible = True
        self.bubble._state = "transcribing"
        self.bubble._tick()
        self.mock_canvas.coords.assert_called()
        self.mock_canvas.itemconfigure.assert_called()

    def test_drag_and_move_callback(self):
        on_move_mock = MagicMock()
        self.bubble.on_move = on_move_mock
        self.mock_win.winfo_x.return_value = 350
        self.mock_win.winfo_y.return_value = 450

        # Press
        self.bubble._on_press(DummyEvent(20, 20))
        self.assertEqual(self.bubble._drag, (20, 20))

        # Drag
        self.bubble._on_drag(DummyEvent(0, 0, x_root=370, y_root=470))
        self.assertTrue(self.bubble._drag_moved)
        self.mock_win.geometry.assert_called_with("+350+450")

        # Release
        self.bubble._on_release(DummyEvent(0, 0))
        self.assertFalse(self.bubble._drag_moved)
        self.assertEqual(self.bubble.pos, (350, 450))
        on_move_mock.assert_called_once_with(350, 450)

    def test_fade_out_and_hide(self):
        self.bubble._visible = True
        self.bubble._alpha = 0.20
        self.bubble._fade_out()
        self.mock_win.attributes.assert_called()

        self.bubble._alpha = 0.03
        self.bubble._fade_out()
        self.assertFalse(self.bubble._visible)
        self.assertEqual(self.bubble._state, "hidden")

if __name__ == "__main__":
    unittest.main()
