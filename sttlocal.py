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

    def snapshot_to_wav(self, output_dir: Path, prefix: str = "preview",
                        tail_seconds: float | None = None) -> Path | None:
        """Write what has been recorded so far, without stopping the recording.

        `tail_seconds` keeps only the end of it. The live preview transcribes
        these snapshots while the user is still speaking, so their cost has to
        stay flat: transcribing everything since the start would get slower
        with every second of a long dictation, and would eventually still be
        running when the user stops -- delaying the real transcription, which
        is the one that matters.
        """
        with self._lock:
            frames = [frame.copy() for frame in self.frames]
        if not frames or self.duration < 0.25:
            return None
        if tail_seconds:
            wanted = int(tail_seconds * self.sample_rate)
            kept: list[np.ndarray] = []
            total = 0
            for frame in reversed(frames):
                kept.append(frame)
                total += frame.shape[0]
                if total >= wanted:
                    break
            frames = list(reversed(kept))
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

    Kept for backward compatibility with ``dictate.py``: the
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
        self, path: Path, hotwords: str | None = None, initial_prompt: str | None = None,
        task: str = "transcribe",
    ) -> TranscriptionResult:
        self.load()
        assert self._transcriber is not None
        return self._transcriber.transcribe(
            path, hotwords=hotwords, initial_prompt=initial_prompt, task=task
        )

    def transcribe(
        self, path: Path, hotwords: str | None = None, initial_prompt: str | None = None,
        task: str = "transcribe",
    ) -> tuple[str, float, str, float]:
        result = self.transcribe_full(path, hotwords, initial_prompt, task)
        return result.text, result.elapsed, result.language, result.language_probability


FILLER_RE = re.compile(
    r"\b(?:euh+|heu+|hum+|hmm+|bah|ben|du coup du coup|voila voila)\b[, ]*",
    flags=re.IGNORECASE,
)
SPACE_RE = re.compile(r"\s+")
REPEATED_WORD_RE = re.compile(r"\b(\w{2,})(?:\s+\1\b){1,3}", flags=re.IGNORECASE)
# Spoken commands, as (spoken forms, action). Order matters: the alternation
# is tried in order, so every phrase must come before any phrase it starts
# with -- "points de suspension" and "point virgule" before "point", "deux
# points" before "points". Getting this wrong turns "points de suspension"
# into ". s de suspension", which is exactly the kind of bug that makes people
# stop trusting dictation.
_COMMANDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    # --- structure ---------------------------------------------------------
    (("nouveau paragraphe", "nouveau paragraph", "paragraphe suivant",
      "double saut de ligne", "saut de ligne"), "insert", "\n\n"),
    (("nouvelle ligne", "nouvel ligne", "a la ligne", "à la ligne",
      "aller a la ligne", "aller à la ligne", "retour a la ligne",
      "retour à la ligne", "retour ligne", "ligne suivante"), "insert", "\n"),
    (("nouvelle puce", "puce", "tiret"), "bullet", "\n- "),
    # --- edition (must be tried before the punctuation that shares a prefix)
    (("tout effacer", "efface tout", "annuler", "annule"), "clear", ""),
    (("effacer le dernier mot", "efface le dernier mot", "effacer le mot",
      "efface le mot", "effacer", "efface"), "del_word", ""),
    # --- punctuation -------------------------------------------------------
    (("points de suspension", "point de suspension"), "insert", "… "),
    (("point d'interrogation", "point dinterrogation"), "insert", "? "),
    (("point d'exclamation", "point dexclamation"), "insert", "! "),
    (("point virgule", "point-virgule"), "insert", "; "),
    (("deux points", "deux-points"), "insert", ": "),
    (("ouvrez les guillemets", "ouvrir les guillemets", "ouvre les guillemets",
      "ouvrez la guillemet"), "insert", " « "),
    (("fermez les guillemets", "fermer les guillemets", "ferme les guillemets",
      "fermez la guillemet"), "insert", " » "),
    (("ouvrez la parenthese", "ouvrez la parenthèse", "ouvrir la parenthese",
      "ouvrir la parenthèse", "ouvrez les parentheses", "ouvrez les parenthèses",
      "ouvre la parenthese", "ouvre la parenthèse"), "insert", " ("),
    (("fermez la parenthese", "fermez la parenthèse", "fermer la parenthese",
      "fermer la parenthèse", "fermez les parentheses", "fermez les parenthèses",
      "ferme la parenthese", "ferme la parenthèse"), "insert", ") "),
    (("virgule",), "insert", ", "),
    (("point",), "insert", ". "),
)

_COMMAND_RE = re.compile(
    r"\s*\b(" + "|".join(
        re.escape(phrase) for phrases, _kind, _value in _COMMANDS for phrase in phrases
    ) + r")\b[\s,]*",
    re.IGNORECASE,
)
_ACTIONS = {
    phrase.lower(): (kind, value)
    for phrases, kind, value in _COMMANDS
    for phrase in phrases
}
_SENTENCE_END_RE = re.compile(r"([.!?…]\s+|\n\n|\n- |^)([a-zà-öø-ÿ])")


def _delete_last_word(text: str) -> str:
    """Drop the last word, and any punctuation that trailed it."""
    stripped = text.rstrip()
    stripped = re.sub(r"[\s,;:.!?…»)\"']+$", "", stripped)
    cut = re.search(r"[\s\n]([^\s\n]+)$", stripped)
    if cut is None:
        return ""
    return stripped[: cut.start()] + " "


def apply_spoken_commands(text: str) -> str:
    """Turn spoken punctuation, layout and edit commands into real text.

    Punctuation and layout are substitutions, but the edit commands are not:
    "effacer" has to remove what was already dictated, so the text is folded
    left to right rather than regex-replaced in place.
    """
    parts = _COMMAND_RE.split(text)
    out = parts[0] if parts else ""
    # split() with one capturing group yields [text, command, text, ...].
    for index in range(1, len(parts), 2):
        command = parts[index].lower()
        tail = parts[index + 1] if index + 1 < len(parts) else ""
        kind, value = _ACTIONS.get(command, ("insert", ""))
        if kind == "clear":
            out = ""
        elif kind == "del_word":
            out = _delete_last_word(out)
        elif kind == "bullet":
            out = out.rstrip() + ("\n- " if out.strip() else "- ")
        else:
            out = out.rstrip() + value
        out += tail

    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n[ \t]+", "\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([,;:.!?…])", r"\1", out)
    out = re.sub(r"([,;:!?…])(?=[^\s\n])", r"\1 ", out)
    # French typography: the "high" punctuation marks take a space before them,
    # the low ones do not. Dictated text goes into emails, so getting this
    # wrong is visible to whoever receives them.
    out = re.sub(r"(?<=[^\s])([;:!?»])", r" \1", out)
    out = re.sub(r"(«)(?=[^\s])", r"\1 ", out)
    out = re.sub(r"\(\s+", "(", out)
    out = re.sub(r"\s+\)", ")", out)
    out = re.sub(r"«\s+", "« ", out)
    out = re.sub(r"\s+»", " »", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # A new sentence, line or bullet starts with a capital.
    out = _SENTENCE_END_RE.sub(lambda m: m.group(1) + m.group(2).upper(), out)
    return out.strip()


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
