import re
import time
import wave
from pathlib import Path
from threading import Lock

import numpy as np
import sounddevice as sd
from pynput import keyboard

from backends import Transcriber, TranscriptionResult, create_backend


SAMPLE_RATE = 16000
CHANNELS = 1


class Recorder:
    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.frames: list[np.ndarray] = []
        self.stream: sd.InputStream | None = None
        self.started_at: float | None = None
        self._lock = Lock()
        self._level = 0.0  # smoothed mic level in [0, 1], for the UI meter

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[audio] {status}")
        # Smoothed RMS level for the listening bubble (cheap, lock-free read).
        block = np.asarray(indata, dtype=np.float32)
        if block.size:
            rms = float(np.sqrt(np.mean(np.square(block))))
            self._level = 0.55 * self._level + 0.45 * min(1.0, rms * 8.0)
        with self._lock:
            self.frames.append(indata.copy())

    def current_level(self) -> float:
        """Latest smoothed microphone level in [0, 1] (0 when not recording)."""
        return self._level if self.stream is not None else 0.0

    @property
    def is_recording(self) -> bool:
        return self.stream is not None

    @property
    def duration(self) -> float:
        if self.started_at is None:
            return 0.0
        return time.perf_counter() - self.started_at

    def start(self) -> None:
        if self.stream is not None:
            return
        with self._lock:
            self.frames = []
        self._level = 0.0
        self.started_at = time.perf_counter()
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def snapshot_to_wav(self, output_dir: Path, prefix: str = "preview") -> Path | None:
        with self._lock:
            frames = [frame.copy() for frame in self.frames]
        if not frames or self.duration < 0.25:
            return None
        return write_frames_to_wav(frames, output_dir, self.sample_rate, prefix)

    def stop_to_wav(self, output_dir: Path) -> Path | None:
        if self.stream is None:
            return None
        self.stream.stop()
        self.stream.close()
        self.stream = None

        duration = self.duration
        self.started_at = None
        with self._lock:
            frames = [frame.copy() for frame in self.frames]
            self.frames = []

        if not frames or duration < 0.25:
            print("Recording too short, ignored.")
            return None

        path = write_frames_to_wav(frames, output_dir, self.sample_rate, "recording")
        print(f"Recorded {duration:.1f}s -> {path}")
        return path


def write_frames_to_wav(frames: list[np.ndarray], output_dir: Path, sample_rate: int, prefix: str) -> Path:
    audio = np.concatenate(frames, axis=0).reshape(-1)
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767).astype(np.int16)

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{prefix}-{int(time.time() * 1000)}.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())

    return path


class DictationEngine:
    """Thin adapter over a pluggable :class:`~backends.Transcriber`.

    Kept for backward compatibility with ``dictate.py`` / ``tray_app.py``: the
    ``transcribe`` method still returns the legacy ``(text, elapsed, language,
    probability)`` tuple. Pick the engine with ``backend`` ("faster-whisper" or
    "openvino").
    """

    def __init__(
        self,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = "fr",
        backend: str = "faster-whisper",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.backend = backend
        self._transcriber: Transcriber | None = None

    @property
    def is_loaded(self) -> bool:
        return self._transcriber is not None and getattr(self._transcriber, "is_loaded", False)

    def load(self) -> None:
        if self._transcriber is None:
            self._transcriber = create_backend(
                self.backend,
                self.model_name,
                self.device,
                self.compute_type,
                self.language,
            )
        self._transcriber.load()

    def transcribe_full(
        self, path: Path, hotwords: str | None = None, initial_prompt: str | None = None
    ) -> TranscriptionResult:
        self.load()
        assert self._transcriber is not None
        return self._transcriber.transcribe(path, hotwords=hotwords, initial_prompt=initial_prompt)

    def transcribe(
        self, path: Path, hotwords: str | None = None, initial_prompt: str | None = None
    ) -> tuple[str, float, str, float]:
        result = self.transcribe_full(path, hotwords, initial_prompt)
        return result.text, result.elapsed, result.language, result.language_probability


FILLER_RE = re.compile(
    r"\b(?:euh+|heu+|hum+|hmm+|bah|ben|du coup du coup|voila voila)\b[, ]*",
    flags=re.IGNORECASE,
)
SPACE_RE = re.compile(r"\s+")
REPEATED_WORD_RE = re.compile(r"\b(\w{2,})(?:\s+\1\b){1,3}", flags=re.IGNORECASE)
COMMAND_REPLACEMENTS = (
    (re.compile(r"\s*\b(?:nouvelle ligne|a la ligne|à la ligne)\b\s*", re.IGNORECASE), "\n"),
    (re.compile(r"\s*\b(?:nouveau paragraphe)\b\s*", re.IGNORECASE), "\n\n"),
    (re.compile(r"\s*\bpoint d'interrogation\b\s*", re.IGNORECASE), "? "),
    (re.compile(r"\s*\bpoint d'exclamation\b\s*", re.IGNORECASE), "! "),
    (re.compile(r"\s*\bdeux points\b\s*", re.IGNORECASE), ": "),
    (re.compile(r"\s*\bpoint virgule\b\s*", re.IGNORECASE), "; "),
    (re.compile(r"\s*\bvirgule\b\s*", re.IGNORECASE), ", "),
    (re.compile(r"\s*\bpoint\b\s*", re.IGNORECASE), ". "),
)


def apply_spoken_commands(text: str) -> str:
    """Turn common spoken punctuation/layout commands into text.

    This deliberately stays small and predictable. It is meant for dictation
    commands ("nouvelle ligne", "virgule"), not full voice control.
    """
    for pattern, replacement in COMMAND_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"([,;:!?])\s+", r"\1 ", text)
    text = re.sub(r"\.\s+", ". ", text)
    return text.strip()


def clean_transcript(text: str, mode: str = "light") -> str:
    text = SPACE_RE.sub(" ", text).strip()
    if not text:
        return ""

    if mode in {"light", "strong"}:
        text = FILLER_RE.sub("", text)
        text = REPEATED_WORD_RE.sub(r"\1", text)
        text = SPACE_RE.sub(" ", text).strip(" ,")

    if mode == "strong":
        text = re.sub(r"\b(je veux dire|tu vois|en fait)\b[, ]*", "", text, flags=re.IGNORECASE)
        text = SPACE_RE.sub(" ", text).strip(" ,")

    text = apply_spoken_commands(text)

    if text and text[-1] not in ".!?;:":
        text += "."
    if text:
        text = text[0].upper() + text[1:]
    return text


def copy_text(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)


def paste_text(text: str) -> None:
    copy_text(text)
    controller = keyboard.Controller()
    with controller.pressed(keyboard.Key.ctrl):
        controller.press("v")
        controller.release("v")
