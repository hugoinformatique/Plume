"""Persistent config + user paths for Plume.

Settings and the correction dictionary live in a per-user JSON file
(%APPDATA%/Plume on Windows, ~/.config/plume elsewhere), so they survive
reinstalls of the app.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


APP_DIR_NAME = "Plume"
_LOG_MAX_BYTES = 1_000_000
# Saves come from several threads (UI bridge, transcription worker, tray).
_SAVE_LOCK = threading.Lock()

DEFAULTS = {
    "language": "fr",
    "model": "small",
    "backend": "faster-whisper",
    "device": "cpu",
    "compute": "int8",
    "cleanup": "light",
    "bubble_position": "bottom",
    "bubble_xy": None,             # [x, y] once the user has dragged the bubble
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


def debug_log(message: str) -> None:
    """Minimal, always-on diagnostic trail for the handful of events that
    have been hardest to reason about from user reports alone (hotkey mode,
    settings writes, single-instance checks) -- independent of the
    JS<->Python bridge and of whether devtools are enabled, so it's always
    available as ground truth. It lives here rather than in plume.py so that
    config writes -- the failures users actually report -- can be traced.

    Rotated at 1 MB (one generation kept): it now traces every UI action and
    every hotkey activation, which would otherwise grow without bound in the
    user's %APPDATA%."""
    try:
        path = config_dir() / "debug.log"
        try:
            if path.stat().st_size > _LOG_MAX_BYTES:
                path.replace(path.with_suffix(".log.1"))
        except FileNotFoundError:
            pass
        line = f"{datetime.now().strftime('%H:%M:%S')} — {message}\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


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
            except Exception as exc:
                # A corrupt file would otherwise silently look like "all my
                # settings reset". Move it aside so the next save() starts from
                # a clean slate instead of failing to parse again forever.
                debug_log(f"config load FAILED: {type(exc).__name__}: {exc} ({path})")
                try:
                    path.replace(path.with_suffix(".json.bad"))
                except Exception as exc2:
                    debug_log(f"could not quarantine bad config: {type(exc2).__name__}: {exc2}")
        return cls(data)

    def save(self) -> bool:
        with _SAVE_LOCK:
            return self._save()

    def _save(self) -> bool:
        # Write-then-rename instead of writing the file in place: an
        # interrupted write (crash, forced kill, antivirus scan mid-write)
        # can otherwise leave config.json truncated, which makes the next
        # load() silently fall back to full DEFAULTS and looks like every
        # setting got reset. os.replace is atomic on the same filesystem.
        #
        # On Windows the replace itself can fail transiently: antivirus or the
        # search indexer may hold the target open for a few dozen ms. Hence the
        # retries, then a last-resort in-place write (losing atomicity beats
        # losing the user's settings), then a logged failure -- never silence.
        #
        # The temp name carries the pid: a dictation finishing (history write,
        # worker thread) while the user flips a setting (bridge thread) had two
        # saves racing on one shared config.json.tmp, and the loser fell all the
        # way through to the non-atomic path for no reason.
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        try:
            tmp.write_text(payload, encoding="utf-8")
            last: Exception | None = None
            for attempt in range(3):
                try:
                    os.replace(tmp, self.path)
                    debug_log(f"config saved: {self.path} ({len(self.data)} keys)")
                    return True
                except Exception as exc:
                    last = exc
                    time.sleep(0.15)
            debug_log(f"config replace failed after 3 tries ({type(last).__name__}: {last}), writing in place")
            self.path.write_text(payload, encoding="utf-8")
            debug_log(f"config saved: {self.path} ({len(self.data)} keys)")
            return True
        except Exception as exc:
            debug_log(f"config save FAILED: {type(exc).__name__}: {exc} ({str(self.path)})")
            return False
        finally:
            # Never leave a stray .tmp behind: it confuses users looking at the
            # config dir, and a leftover from a crashed run is meaningless.
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value) -> bool:
        self.data[key] = value
        ok = self.save()
        # history/vocabulary can be thousands of characters; log their size only.
        shown = f"{len(value)} items" if key in ("history", "vocabulary") else repr(value)
        debug_log(f"config set: {key}={shown} -> {'ok' if ok else 'FAILED'}")
        return ok

    def reload_from_disk(self) -> dict:
        """What is actually persisted right now -- used to check that a write
        landed, rather than trusting the in-memory copy."""
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def verify(self, key, default=None):
        """Value of `key` as stored on disk, DEFAULTS otherwise."""
        return self.reload_from_disk().get(key, DEFAULTS.get(key, default))


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
