"""Persistent config + user paths for Plume.

Settings and the correction dictionary live in a per-user JSON file
(%APPDATA%/Plume on Windows, ~/.config/plume elsewhere), so they survive
reinstalls of the app.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


APP_DIR_NAME = "Plume"

DEFAULTS = {
    "language": "fr",
    "model": "small",
    "backend": "faster-whisper",
    "device": "cpu",
    "compute": "int8",
    "cleanup": "light",
    "bubble_position": "bottom",
    "hotkey": "<ctrl>+<space>",   # pynput format
    "hotkey_display": "Ctrl + Espace",
    "autopaste": True,
    "autostart": False,
    "metrics": True,               # benchmark log (removable later)
    "push_to_talk": False,         # hold hotkey to record instead of press-to-toggle
    "sound_feedback": True,        # short beep on start/stop, independent of the bubble
    "vocabulary": [],              # list of {"from": str, "to": str}
    "history": [],                 # last local dictations, never leaves the PC
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = Path(base) / APP_DIR_NAME
    else:
        path = Path(os.path.expanduser("~/.config/plume"))
    path.mkdir(parents=True, exist_ok=True)
    return path


class Config:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.path = config_dir() / "config.json"

    @classmethod
    def load(cls) -> "Config":
        path = config_dir() / "config.json"
        data = dict(DEFAULTS)
        if path.exists():
            try:
                data.update(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cls(data)

    def save(self) -> None:
        # Write-then-rename instead of writing the file in place: an
        # interrupted write (crash, forced kill, antivirus scan mid-write)
        # can otherwise leave config.json truncated, which makes the next
        # load() silently fall back to full DEFAULTS and looks like every
        # setting got reset. os.replace is atomic on the same filesystem.
        try:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception:
            pass

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value) -> None:
        self.data[key] = value
        self.save()


# ---- hotkey display <-> pynput format ---------------------------------------
_DISP_TO_PYNPUT = {
    "ctrl": "<ctrl>", "control": "<ctrl>", "alt": "<alt>", "option": "<alt>",
    "maj": "<shift>", "shift": "<shift>", "cmd": "<cmd>", "win": "<cmd>",
    "espace": "<space>", "space": "<space>", "entrée": "<enter>", "enter": "<enter>",
    "tab": "<tab>", "échap": "<esc>", "echap": "<esc>", "escape": "<esc>",
    "haut": "<up>", "bas": "<down>", "gauche": "<left>", "droite": "<right>",
}


def hotkey_to_pynput(display: str) -> str:
    """'Ctrl + Espace' -> '<ctrl>+<space>' ; 'F9' -> '<f9>'."""
    parts = [p.strip() for p in display.replace("+", " ").split() if p.strip()]
    out = []
    for p in parts:
        low = p.lower()
        if low in _DISP_TO_PYNPUT:
            out.append(_DISP_TO_PYNPUT[low])
        elif len(p) == 1:
            out.append(low)
        elif low.startswith("f") and low[1:].isdigit():
            out.append(f"<{low}>")
        else:
            out.append(f"<{low}>")
    return "+".join(out) if out else "<ctrl>+<space>"
