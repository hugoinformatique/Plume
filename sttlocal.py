import re
import time
import wave
from pathlib import Path
from threading import Lock

import numpy as np
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
        self._lock = Lock()

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[audio] {status}")
        with self._lock:
            self.frames.append(indata.copy())

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
    def __init__(
        self,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = "fr",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model: WhisperModel | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is None:
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )

    def transcribe(self, path: Path) -> tuple[str, float, str, float]:
        self.load()
        assert self._model is not None
        started = time.perf_counter()
        segments, info = self._model.transcribe(
            str(path),
            language=self.language,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        elapsed = time.perf_counter() - started
        return text, elapsed, info.language, info.language_probability


FILLER_RE = re.compile(
    r"\b(?:euh+|heu+|hum+|hmm+|bah|ben|du coup du coup|voila voila)\b[, ]*",
    flags=re.IGNORECASE,
)
SPACE_RE = re.compile(r"\s+")
REPEATED_WORD_RE = re.compile(r"\b(\w{2,})(?:\s+\1\b){1,3}", flags=re.IGNORECASE)


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

    if text and text[-1] not in ".!?;:":
        text += "."
    if text:
        text = text[0].upper() + text[1:]
    return text


def paste_text(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)
    controller = keyboard.Controller()
    with controller.pressed(keyboard.Key.ctrl):
        controller.press("v")
        controller.release("v")
