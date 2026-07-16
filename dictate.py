import argparse
import queue
from pathlib import Path

from pynput import keyboard

from sttlocal import DictationEngine, Recorder, clean_transcript, paste_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Whisper dictation MVP")
    parser.add_argument("--model", default="small", help="Whisper model: base, small, medium, turbo, etc. For openvino, a converted model directory.")
    parser.add_argument("--language", default="fr", help="Language code, e.g. fr or en. Use auto for detection.")
    parser.add_argument("--backend", default="faster-whisper", choices=["faster-whisper", "openvino"], help="STT engine")
    parser.add_argument("--device", default="cpu", help="Device. faster-whisper: cpu/cuda. openvino: CPU/GPU/NPU.")
    parser.add_argument("--compute-type", default="int8", help="faster-whisper compute type, default int8")
    parser.add_argument("--cleanup", default="light", choices=["off", "light", "strong"], help="Text cleanup mode")
    parser.add_argument("--recordings-dir", default="recordings", help="Where recordings are stored")
    args = parser.parse_args()

    language = None if args.language.lower() == "auto" else args.language
    recordings_dir = Path(args.recordings_dir)

    print("Loading model...")
    print(f"backend={args.backend} model={args.model} device={args.device} compute_type={args.compute_type} language={language or 'auto'}")
    engine = DictationEngine(args.model, args.device, args.compute_type, language, backend=args.backend)
    engine.load()
    recorder = Recorder()
    actions: queue.Queue[str] = queue.Queue()

    def on_toggle() -> None:
        actions.put("toggle")

    def on_quit() -> None:
        actions.put("quit")

    hotkeys = keyboard.GlobalHotKeys({
        "<f9>": on_toggle,
        "<esc>": on_quit,
    })
    hotkeys.start()

    print("Ready. F9=start/stop, Esc=quit.")

    try:
        while True:
            action = actions.get()
            if action == "quit":
                print("Quit requested.")
                break

            if not recorder.is_recording:
                recorder.start()
                continue

            path = recorder.stop_to_wav(recordings_dir)
            if path is None:
                continue

            raw_text, elapsed, detected_language, probability = engine.transcribe(path)
            text = raw_text if args.cleanup == "off" else clean_transcript(raw_text, args.cleanup)
            print(
                f"Detected language={detected_language} prob={probability:.2f}; "
                f"transcription={elapsed:.2f}s"
            )
            if not text:
                print("No text detected.")
                continue

            print(f"Text: {text}")
            paste_text(text)
            print("Pasted into active app.")

    finally:
        hotkeys.stop()
        if recorder.is_recording:
            recorder.stop_to_wav(recordings_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
