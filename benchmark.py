import argparse
import csv
import time
from pathlib import Path

from faster_whisper import WhisperModel


SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


def audio_files(samples_dir: Path) -> list[Path]:
    if not samples_dir.exists():
        return []
    return sorted(path for path in samples_dir.iterdir() if path.suffix.lower() in SUPPORTED_EXTENSIONS)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark faster-whisper models on local samples")
    parser.add_argument("--models", nargs="+", default=["base", "small"], help="Models to benchmark")
    parser.add_argument("--language", default="fr", help="Language code, e.g. fr or en. Use auto for detection.")
    parser.add_argument("--device", default="cpu", help="faster-whisper device, default cpu")
    parser.add_argument("--compute-type", default="int8", help="faster-whisper compute type, default int8")
    parser.add_argument("--samples-dir", default="samples", help="Input audio folder")
    parser.add_argument("--output-dir", default="benchmark-results", help="Output folder")
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
    for model_name in args.models:
        print(f"Loading {model_name}...")
        model = WhisperModel(model_name, device=args.device, compute_type=args.compute_type)
        for path in files:
            started = time.perf_counter()
            segments, info = model.transcribe(
                str(path),
                language=language,
                vad_filter=True,
                beam_size=5,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            elapsed = time.perf_counter() - started
            row = {
                "model": model_name,
                "file": path.name,
                "seconds": f"{elapsed:.3f}",
                "language": info.language,
                "language_probability": f"{info.language_probability:.3f}",
                "chars": len(text),
                "text": text,
            }
            rows.append(row)
            print(f"{model_name} {path.name}: {elapsed:.2f}s -> {text[:120]}")

    with results_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "model",
                "file",
                "seconds",
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
