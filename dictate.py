import argparse
import os
import queue
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import pyperclip
import sounddevice as sd
from faster_whisper import WhisperModel
from pynput import keyboard


SAMPLE_RATE = 16000
CHANNELS = 1


class Recorder:
    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.frames: list[np.ndarray] = []
        self.stream: sd.InputStream | None = None
        self.started_at: float | None = None

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[audio] {status}")
        self.frames.append(indata.copy())

    @property
    def is_recording(self) -> bool:
        return self.stream is not None

    def start(self) -> None:
        if self.stream is not None:
            return
        self.frames = []
        self.started_at = time.perf_counter()
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()
        print("Recording... press F9 again to stop.")

    def stop_to_wav(self, output_dir: Path) -> Path | None:
        if self.stream is None:
            return None
        self.stream.stop()
        self.stream.close()
        self.stream = None

        duration = time.perf_counter() - (self.started_at or time.perf_counter())
        if not self.frames or duration < 0.25:
            print("Recording too short, ignored.")
            return None

        audio = np.concatenate(self.frames, axis=0).reshape(-1)
        audio = np.clip(audio, -1.0, 1.0)
        pcm = (audio * 32767).astype(np.int16)

        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"recording-{int(time.time())}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            wav.writeframes(pcm.tobytes())

        print(f"Recorded {duration:.1f}s -> {path}")
        return path


def paste_text(text: str) -> None:
    pyperclip.copy(text)
    controller = keyboard.Controller()
    with controller.pressed(keyboard.Key.ctrl):
        controller.press("v")
        controller.release("v")


def transcribe(model: WhisperModel, path: Path, language: str | None) -> tuple[str, float]:
    started = time.perf_counter()
    segments, info = model.transcribe(
        str(path),
        language=language,
        vad_filter=True,
        beam_size=5,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    elapsed = time.perf_counter() - started
    print(
        f"Detected language={info.language} prob={info.language_probability:.2f}; "
        f"transcription={elapsed:.2f}s"
    )
    return text, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Whisper dictation MVP")
    parser.add_argument("--model", default="small", help="Whisper model: base, small, medium, turbo, etc.")
    parser.add_argument("--language", default="fr", help="Language code, e.g. fr or en. Use auto for detection.")
    parser.add_argument("--device", default="cpu", help="faster-whisper device, default cpu")
    parser.add_argument("--compute-type", default="int8", help="faster-whisper compute type, default int8")
    parser.add_argument("--recordings-dir", default="recordings", help="Where recordings are stored")
    args = parser.parse_args()

    language = None if args.language.lower() == "auto" else args.language
    recordings_dir = Path(args.recordings_dir)

    print("Loading model...")
    print(f"model={args.model} device={args.device} compute_type={args.compute_type} language={language or 'auto'}")
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
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

            text, elapsed = transcribe(model, path, language)
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
