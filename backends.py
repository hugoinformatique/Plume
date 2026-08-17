"""Pluggable speech-to-text backends for Plume.

Design goal (see project decision): keep a reliable CPU baseline with
``faster-whisper`` and add an interchangeable OpenVINO backend that can target
CPU / GPU (Intel Arc iGPU) / NPU (Intel AI Boost) on Core Ultra machines.

All heavy imports are lazy so importing this module never fails just because a
given backend's dependencies are not installed.
"""

from __future__ import annotations

import os
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


SAMPLE_RATE = 16000


@dataclass
class TranscriptionResult:
    text: str
    elapsed: float
    language: str
    language_probability: float
    audio_seconds: float | None = None  # source audio duration, for RTF

    @property
    def rtf(self) -> float | None:
        """Real-time factor = processing / audio. < 1.0 is faster than real time."""
        if not self.audio_seconds:
            return None
        return self.elapsed / self.audio_seconds


@runtime_checkable
class Transcriber(Protocol):
    """Common interface every backend implements."""

    def load(self) -> None:
        ...

    def transcribe(self, path: Path, hotwords: str | None = None,
                   initial_prompt: str | None = None,
                   task: str = "transcribe") -> TranscriptionResult:
        ...


def read_wav_mono_f32(path: Path, target_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Read a mono/16-bit PCM wav into a float32 array in [-1, 1].

    The Recorder writes exactly this format (16 kHz mono int16), so no
    resampling library is required for the common path. If the file uses a
    different rate we do a light linear resample to keep the dependency
    surface minimal.
    """
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        rate = wav.getframerate()
        width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())

    if width != 2:
        raise ValueError(f"Only 16-bit PCM wav is supported, got {width * 8}-bit")

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    if rate != target_rate and audio.size:
        duration = audio.size / rate
        new_len = int(round(duration * target_rate))
        if new_len > 0:
            src_idx = np.linspace(0, audio.size - 1, num=new_len)
            audio = np.interp(src_idx, np.arange(audio.size), audio).astype(np.float32)

    return audio


class FasterWhisperBackend:
    """Reliable CPU baseline. Wraps ``faster-whisper`` (CTranslate2).

    Note: CTranslate2 targets CPU and NVIDIA GPUs only. It cannot use the
    Intel NPU or iGPU. For those, use :class:`OpenVINOBackend`.
    """

    def __init__(
        self,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = "fr",
        beam_size: int = 5,
        vad: bool = True,
        cpu_threads: int = 0,
        num_workers: int = 1,
        no_speech_threshold: float = 0.6,
        log_prob_threshold: float = -1.0,
        compression_ratio_threshold: float = 2.4,
        **_ignored,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.vad = vad
        # 0 lets CTranslate2 pick a default (all logical cores); pin it
        # explicitly on Windows/Intel hybrid CPUs (P/E/LP cores) so the
        # scheduler doesn't spread threads onto low-power cores.
        self.cpu_threads = cpu_threads or max(1, (os.cpu_count() or 4) - 2)
        self.num_workers = num_workers
        self.no_speech_threshold = no_speech_threshold
        self.log_prob_threshold = log_prob_threshold
        self.compression_ratio_threshold = compression_ratio_threshold
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install -r requirements.txt"
            ) from exc
        self._model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads if self.device == "cpu" else 0,
            num_workers=self.num_workers,
        )

    def transcribe(self, path: Path, hotwords: str | None = None,
                   initial_prompt: str | None = None,
                   task: str = "transcribe") -> TranscriptionResult:
        self.load()
        assert self._model is not None
        started = time.perf_counter()
        segments, info = self._model.transcribe(
            str(path),
            language=self.language,
            # "translate" is Whisper's own second task: it decodes straight to
            # English from the source language, in the same pass. No second
            # model, no network, no added latency.
            task=task if task in ("transcribe", "translate") else "transcribe",
            vad_filter=self.vad,
            beam_size=self.beam_size,
            condition_on_previous_text=False,
            hotwords=hotwords or None,
            initial_prompt=initial_prompt or None,
            no_speech_threshold=self.no_speech_threshold,
            log_prob_threshold=self.log_prob_threshold,
            compression_ratio_threshold=self.compression_ratio_threshold,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        elapsed = time.perf_counter() - started
        audio_seconds = getattr(info, "duration", None)
        return TranscriptionResult(
            text, elapsed, info.language, info.language_probability, audio_seconds
        )


class OpenVINOBackend:
    """Intel OpenVINO GenAI backend. Can target CPU / GPU / NPU.

    ``model_name`` must point to a directory holding an OpenVINO-converted
    Whisper model (IR + tokenizer). Convert once with, e.g.::

        optimum-cli export openvino \\
            --model openai/whisper-small \\
            --weight-format fp16 \\
            models/openvino/whisper-small

    FP16 is what the shipped installer bundles and what the iGPU runs
    natively; int8 mainly buys disk size.

    On NPU the pipeline must be static (``STATIC_PIPELINE=YES``). GPU refers to
    the Intel Arc iGPU on Core Ultra parts, which is often the fastest target
    for Whisper; NPU trades raw speed for low power / heat and a free CPU.
    """

    # device is an OpenVINO target string: "CPU", "GPU", or "NPU".
    def __init__(
        self,
        model_name: str,
        device: str = "CPU",
        compute_type: str = "int8",  # kept for interface symmetry; conversion-time concern
        language: str | None = "fr",
        **_ignored,
    ) -> None:
        self.model_dir = Path(model_name)
        self.device = device.upper()
        self.compute_type = compute_type
        self.language = language
        self._pipeline = None

    @property
    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def _language_token(self) -> str | None:
        if not self.language or self.language.lower() == "auto":
            return None
        return f"<|{self.language.lower()}|>"

    def load(self) -> None:
        if self._pipeline is not None:
            return
        try:
            import openvino_genai as ov_genai
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "openvino-genai is not installed. Run: pip install openvino-genai openvino "
                "(and convert a model with optimum-cli export openvino)."
            ) from exc

        if not self.model_dir.exists():
            raise RuntimeError(
                f"OpenVINO model directory not found: {self.model_dir}\n"
                "Convert one first, e.g.:\n"
                "  optimum-cli export openvino --model openai/whisper-small "
                f"--weight-format fp16 {self.model_dir}"
            )

        kwargs: dict[str, object] = {}
        if self.device == "NPU":
            # NPU requires a static pipeline.
            kwargs["STATIC_PIPELINE"] = "YES"
        self._pipeline = ov_genai.WhisperPipeline(str(self.model_dir), self.device, **kwargs)

    def transcribe(self, path: Path, hotwords: str | None = None,
                   initial_prompt: str | None = None,
                   task: str = "transcribe") -> TranscriptionResult:
        self.load()
        assert self._pipeline is not None
        audio = read_wav_mono_f32(path)

        # On "translate" Whisper still needs the *source* language token: it
        # translates from that language into English.
        if task not in ("transcribe", "translate"):
            task = "transcribe"
        gen_kwargs: dict[str, object] = {"task": task}
        lang_token = self._language_token()
        if lang_token is not None:
            gen_kwargs["language"] = lang_token
        if initial_prompt:
            # Best-effort biasing; ignored by pipelines that don't support it.
            gen_kwargs["initial_prompt"] = initial_prompt

        started = time.perf_counter()
        try:
            result = self._pipeline.generate(audio, **gen_kwargs)
        except Exception:
            gen_kwargs.pop("initial_prompt", None)
            result = self._pipeline.generate(audio, **gen_kwargs)
        elapsed = time.perf_counter() - started

        text = str(result).strip()
        detected = self.language or "auto"
        # OpenVINO GenAI does not expose a language probability; report 1.0 when
        # the language was forced, else unknown (0.0).
        prob = 1.0 if lang_token is not None else 0.0
        audio_seconds = audio.size / SAMPLE_RATE if audio.size else None
        return TranscriptionResult(text, elapsed, detected, prob, audio_seconds)


BACKENDS = {
    "faster-whisper": FasterWhisperBackend,
    "openvino": OpenVINOBackend,
}


def create_backend(
    backend: str,
    model_name: str,
    device: str,
    compute_type: str,
    language: str | None,
    **kwargs,
) -> Transcriber:
    """Factory. ``backend`` is one of :data:`BACKENDS`.

    Device semantics differ per backend:
      - faster-whisper: "cpu" or "cuda"
      - openvino:       "CPU", "GPU", or "NPU"

    Extra kwargs (e.g. ``beam_size``, ``vad``) are forwarded to the backend;
    backends ignore options they don't understand.
    """
    try:
        cls = BACKENDS[backend]
    except KeyError:
        options = ", ".join(sorted(BACKENDS))
        raise ValueError(f"Unknown backend '{backend}'. Available: {options}")
    return cls(
        model_name=model_name,
        device=device,
        compute_type=compute_type,
        language=language,
        **kwargs,
    )
