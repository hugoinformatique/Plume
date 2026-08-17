"""Unit tests for the global shortcut matcher.

    python scripts/test_hotkeys.py

`HotkeyEngine` is extracted from `plume.py` and run against a stub `pynput`,
so the test needs neither a keyboard hook nor a display. What it guards is the
property that broke when a second shortcut appeared: with two combinations
where one contains the other (Ctrl+Space and Ctrl+Shift+Space), exactly one
must match any given key state.
"""

import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _install_fake_pynput():
    class Key:
        ctrl, alt, shift, cmd = "CTRL", "ALT", "SHIFT", "CMD"

    class HotKey:
        @staticmethod
        def parse(combo):
            table = {"<ctrl>": Key.ctrl, "<alt>": Key.alt,
                     "<shift>": Key.shift, "<cmd>": Key.cmd}
            return [table.get(part, part) for part in combo.split("+")]

    keyboard = types.ModuleType("pynput.keyboard")
    keyboard.Key = Key
    keyboard.HotKey = HotKey
    pynput = types.ModuleType("pynput")
    pynput.keyboard = keyboard
    sys.modules["pynput"] = pynput
    sys.modules["pynput.keyboard"] = keyboard
    return HotKey


HotKey = _install_fake_pynput()


def _load_hotkey_engine():
    source = open(os.path.join(ROOT, "plume.py"), encoding="utf-8").read()
    start = source.index("def parse_combo_keys")
    end = source.index("class PlumeApp")
    namespace = {"threading": __import__("threading"), "_debug_log": lambda *a: None}
    exec(compile(source[start:end], "plume.py", "exec"), namespace)
    return namespace["HotkeyEngine"]


HotkeyEngine = _load_hotkey_engine()

DICTATION = "<ctrl>+<space>"
TRANSLATE = "<ctrl>+<shift>+<space>"


class TestHotkeyMatching(unittest.TestCase):
    def setUp(self):
        self.dictation = HotkeyEngine(DICTATION, lambda: None)
        self.translate = HotkeyEngine(TRANSLATE, lambda: None)

    def press(self, combo):
        pressed = set(HotKey.parse(combo))
        self.dictation._pressed = set(pressed)
        self.translate._pressed = set(pressed)
        return self.dictation._matches(), self.translate._matches()

    def test_each_combination_matches_exactly_one_shortcut(self):
        """The bug this replaces: {ctrl, space} is a subset of what is held
        when Ctrl+Shift+Space is pressed, so *both* shortcuts fired and the
        debounce decided which one won."""
        self.assertEqual(self.press(DICTATION), (True, False))
        self.assertEqual(self.press(TRANSLATE), (False, True))

    def test_extra_modifier_matches_nothing(self):
        self.assertEqual(self.press("<ctrl>+<alt>+<space>"), (False, False))

    def test_incomplete_combination_matches_nothing(self):
        self.assertEqual(self.press("<space>"), (False, False))
        self.assertEqual(self.press("<ctrl>"), (False, False))

    def test_non_modifier_extra_key_still_matches(self):
        """Only stray *modifiers* disqualify: holding a letter while the combo
        completes must not silently disable dictation."""
        self.dictation._pressed = set(HotKey.parse(DICTATION)) | {"a"}
        self.assertTrue(self.dictation._matches())

    def test_activation_is_edge_triggered(self):
        fired = []
        engine = HotkeyEngine(DICTATION, lambda: fired.append(1))
        for _ in range(3):  # OS key repeat
            engine._on_press("CTRL")
            engine._on_press("<space>")
        self.assertEqual(len(fired), 1, "key repeat must not re-fire the shortcut")
        engine._on_release("<space>")
        engine._on_press("<space>")
        self.assertEqual(len(fired), 2, "a fresh press must fire again")


if __name__ == "__main__":
    unittest.main(verbosity=2)
