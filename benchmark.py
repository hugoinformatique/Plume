"""Benchmark STT backends/devices/models on local audio samples.

This is the tool that decides, on your real HP Core Ultra machine, whether the
NPU actually beats the Arc iGPU or a plain CPU int8 run for dictation-length
clips. It sweeps every backend x device x model combination over the audio in
``samples/`` and writes latency + real-time-factor (RTF) to a CSV.

Examples:

    # CPU baseline across models
    python benchmark.py --backends faster-whisper --devices cpu \\
        --models base small medium turbo --language fr

    # Compare the OpenVINO targets (needs converted models, see backends.py)
    python benchmark.py --backends openvino --devices CPU GPU NPU \\
        --models models/openvino/whisper-small --language fr

RTF < 1.0 means faster than real time. For dictation, low absolute latency on
short clips matters more than RTF on long files, so keep some short samples too.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from backends import create_backend


SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
OPENVINO_EXTENSIONS = {".wav"}


def audio_files(samples_dir: Path) -> list[Path]:
    if not samples_dir.exists():
        return []
    return sorted(path for path in samples_dir.iterdir() if path.suffix.lower() in SUPPORTED_EXTENSIONS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark STT backends on local samples")
    parser.add_argument("--backends", nargs="+", default=["faster-whisper"], help="Backends: faster-whisper openvino")
    parser.add_argument("--devices", nargs="+", default=["cpu"], help="Devices. faster-whisper: cpu/cuda. openvino: CPU/GPU/NPU")
    parser.add_argument("--models", nargs="+", default=["base", "small"], help="Model names, or converted dirs for openvino")
    parser.add_argument("--language", default="fr", help="Language code, e.g. fr or en. Use auto for detection.")
    parser.add_argument("--compute-type", default="int8", help="faster-whisper compute type, default int8")
    parser.add_argument("--samples-dir", default="samples", help="Input audio folder")
    parser.add_argument("--output-dir", default="benchmark-results", help="Output folder")
    parser.add_argument("--repeats", type=int, default=1, help="Runs per combination (warm timing after load)")
    args = parser.parse_args()

    samples_dir = Path(args.samples_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.csv"
    language = None if args.language.lower() == "auto" else args.language
    files = audio_files(samples_dir)

    if not files:
        print(f"No audio files found in {samples_dir}. Add .wav/.mp3/.m4a samples first.")
        return 2

    rows = []
    for backend_name in args.backends:
        for device in args.devices:
            for model_name in args.models:
                label = f"{backend_name}/{device}/{model_name}"
                print(f"Loading {label} ...")
                try:
                    backend = create_backend(backend_name, model_name, device, args.compute_type, language)
                    backend.load()
                except Exception as exc:  # noqa: BLE001 - report and keep sweeping
                    print(f"  SKIP {label}: {exc}")
                    rows.append({
                        "backend": backend_name, "device": device, "model": model_name,
                        "file": "", "seconds": "", "audio_seconds": "", "rtf": "",
                        "language": "", "language_probability": "", "chars": "",
                        "text": f"ERROR: {exc}",
                    })
                    continue

                for path in files:
                    if backend_name == "openvino" and path.suffix.lower() not in OPENVINO_EXTENSIONS:
                        print(f"  SKIP {label} {path.name}: OpenVINO backend currently expects WAV PCM input")
                        rows.append({
                            "backend": backend_name,
                            "device": device,
                            "model": model_name,
                            "file": path.name,
                            "seconds": "",
                            "audio_seconds": "",
                            "rtf": "",
                            "language": "",
                            "language_probability": "",
                            "chars": "",
                            "text": "SKIP: OpenVINO backend currently expects WAV PCM input",
                        })
                        continue
                    for run in range(args.repeats):
                        try:
                            result = backend.transcribe(path)
                        except Exception as exc:  # noqa: BLE001
                            print(f"  FAIL {label} {path.name}: {exc}")
                            continue
                        rtf = result.rtf
                        rows.append({
                            "backend": backend_name,
                            "device": device,
                            "model": model_name,
                            "file": path.name,
                            "seconds": f"{result.elapsed:.3f}",
                            "audio_seconds": f"{result.audio_seconds:.3f}" if result.audio_seconds else "",
                            "rtf": f"{rtf:.3f}" if rtf is not None else "",
                            "language": result.language,
                            "language_probability": f"{result.language_probability:.3f}",
                            "chars": len(result.text),
                            "text": result.text,
                        })
                        rtf_str = f" rtf={rtf:.2f}" if rtf is not None else ""
                        print(f"  {label} {path.name}: {result.elapsed:.2f}s{rtf_str} -> {result.text[:100]}")

    with results_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "backend",
                "device",
                "model",
                "file",
                "seconds",
                "audio_seconds",
                "rtf",
                "language",
                "language_probability",
                "chars",
                "text",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Results written to {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
