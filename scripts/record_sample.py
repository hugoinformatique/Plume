"""Record a short wav clip into samples/, for benchmark.py.

Usage:
    python scripts/record_sample.py [seconds] [name]

Defaults to 8 seconds, saved as samples/<name>-<timestamp>.wav (wav, 16kHz
mono, the format every backend including OpenVINO can read).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sttlocal import Recorder  # noqa: E402


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
    name = sys.argv[2] if len(sys.argv) > 2 else "sample"

    samples_dir = Path("samples")
    samples_dir.mkdir(parents=True, exist_ok=True)

    recorder = Recorder()
    recorder.start()
    print(f"Enregistrement... parle maintenant ({seconds:.0f}s)")
    time.sleep(seconds)
    path = recorder.stop_to_wav(samples_dir)
    if path is None:
        print("Rien d'enregistre (trop court ou pas de micro detecte).")
        return 1

    target = samples_dir / f"{name}.wav"
    if target.exists():
        target.unlink()
    path.replace(target)
    print(f"Sauvegarde : {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
