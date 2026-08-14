"""Read and summarize the performance history Plume already logs.

plume.py appends one row to ``metrics.csv`` (in the per-user config dir, see
config.config_dir) after every real dictation, when the "metrics" setting is
on. This script turns that raw history into an at-a-glance comparison across
backends/devices/models, so CPU vs NPU vs iGPU and model-size tradeoffs can be
judged from real usage over time instead of a single manual test.

Usage:

    python perflog.py --summary          # aggregated stats by backend/device/model
    python perflog.py --tail 20          # last 20 raw rows
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from statistics import mean

from config import config_dir


def _read_rows(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    with log_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summarize(log_path: Path) -> None:
    rows = _read_rows(log_path)
    if not rows:
        print(f"No metrics in {log_path} yet (dictate a bit first, or check the 'metrics' setting).")
        return

    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (row.get("backend", ""), row.get("device", ""), row.get("model", ""))
        groups.setdefault(key, []).append(row)

    print(f"{'backend':<14} {'device':<7} {'model':<8} {'runs':>5} {'avg_s':>7} {'avg_rtf':>8}")
    for (backend, device, model), group_rows in sorted(groups.items()):
        elapsed = [float(r["elapsed_s"]) for r in group_rows if r.get("elapsed_s")]
        rtfs = [float(r["rtf"]) for r in group_rows if r.get("rtf")]
        avg_elapsed = f"{mean(elapsed):.2f}" if elapsed else "-"
        # rtf here is elapsed/audio (TranscriptionResult.rtf); lower is faster.
        avg_rtf = f"{mean(rtfs):.2f}" if rtfs else "-"
        print(f"{backend:<14} {device:<7} {model:<8} {len(group_rows):>5} {avg_elapsed:>7} {avg_rtf:>8}")


def tail(log_path: Path, n: int) -> None:
    rows = _read_rows(log_path)
    for row in rows[-n:]:
        print(
            f"{row.get('timestamp', '')} {row.get('backend', ''):<14} "
            f"{row.get('device', ''):<6} {row.get('model', ''):<8} "
            f"{row.get('elapsed_s', '')}s rtf={row.get('rtf', '')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Plume's local performance history (metrics.csv)")
    parser.add_argument("--log-path", default=str(config_dir() / "metrics.csv"))
    parser.add_argument("--summary", action="store_true", help="Aggregated stats by backend/device/model")
    parser.add_argument("--tail", type=int, default=0, help="Show the last N raw rows")
    args = parser.parse_args()

    log_path = Path(args.log_path)
    if args.summary or not args.tail:
        summarize(log_path)
    if args.tail:
        tail(log_path, args.tail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
