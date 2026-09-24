"""Local faster-whisper wrapper with CUDA-first startup and CPU fallback."""
from __future__ import annotations

import ctypes
import logging
import math
import os
from pathlib import Path
from typing import Callable

import numpy as np

from app.config import WhisperConfig

LOGGER = logging.getLogger(__name__)


class WhisperEngine:
    def __init__(self, config: WhisperConfig, vocabulary_file: Path) -> None:
        self.config, self.vocabulary_file = config, vocabulary_file
        self.model = None
        self.active_device = "not loaded"
        self._cuda_dll_directory = None
        self._cuda_dlls: list[object] = []

    def load(self) -> None:
        self._prepare_cuda_runtime()
        from faster_whisper import WhisperModel
        requested = self.config.device
        try:
            self.model = WhisperModel(self.config.model, device=requested, compute_type=self.config.compute_type)
            self.active_device = requested
        except Exception as exc:
            if requested != "cuda":
                raise
            self._load_cpu_fallback(exc)
        LOGGER.info("Whisper loaded: %s on %s", self.config.model, self.active_device)

    def _prepare_cuda_runtime(self) -> None:
        if os.name != "nt" or self.config.device != "cuda" or self._cuda_dll_directory is not None:
            return
        runtime_dir = Path(__file__).resolve().parents[2] / "vendor" / "cuda"
        if not runtime_dir.is_dir():
            return
        self._cuda_dll_directory = os.add_dll_directory(str(runtime_dir))
        dll_names = (
            "cublasLt64_12.dll", "cublas64_12.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll",
            "cudnn_graph64_9.dll", "cudnn_heuristic64_9.dll", "cudnn_engines_precompiled64_9.dll",
            "cudnn_engines_runtime_compiled64_9.dll", "cudnn_adv64_9.dll", "cudnn_cnn64_9.dll",
        )
        try:
            self._cuda_dlls = [ctypes.WinDLL(str(runtime_dir / name)) for name in dll_names]
        except OSError as exc:
            self._cuda_dlls.clear()
            LOGGER.warning("Bundled CUDA runtime could not be preloaded: %s", exc)
        LOGGER.info("Using bundled CUDA runtime: %s", runtime_dir)

    def transcribe(self, audio: np.ndarray) -> list[tuple[str, float | None]]:
        if self.model is None:
            raise RuntimeError("Whisper model not loaded")
        try:
            return self._transcribe(audio)
        except RuntimeError as exc:
            if self.active_device != "cuda":
                raise
            self._load_cpu_fallback(exc)
            return self._transcribe(audio)

    def _load_cpu_fallback(self, cause: Exception) -> None:
        from faster_whisper import WhisperModel

        LOGGER.warning("CUDA Whisper failed; falling back to CPU: %s", cause)
        self.model = WhisperModel(self.config.model, device="cpu", compute_type="int8")
        self.active_device = "cpu (CUDA fallback)"
        LOGGER.info("Whisper loaded: %s on %s", self.config.model, self.active_device)

    def _transcribe(self, audio: np.ndarray) -> list[tuple[str, float | None]]:
        prompt = self._vocabulary_prompt()
        segments, _ = self.model.transcribe(
            audio, language=self.config.language or None, beam_size=1,
            vad_filter=self.config.vad,
            vad_parameters={"threshold": 0.65, "min_speech_duration_ms": 200, "speech_pad_ms": 200}
            if self.config.vad else None,
            initial_prompt=prompt or None, condition_on_previous_text=False,
        )
        results: list[tuple[str, float | None]] = []
        audio_seconds = len(audio) / 16000
        for segment in segments:
            text = segment.text.strip()
            if not text or not self._segment_is_plausible(segment):
                continue
            confidence = math.exp(segment.avg_logprob) if segment.avg_logprob is not None else None
            results.append((text, round(min(1.0, confidence), 3) if confidence is not None else None))
        max_characters = max(90, round(audio_seconds * 55))
        max_segments = max(3, round(audio_seconds * 2))
        if len(results) > max_segments or sum(len(text) for text, _ in results) > max_characters:
            LOGGER.warning("Discarded implausibly dense Whisper output (%d segments, %d characters in %.2fs)",
                           len(results), sum(len(text) for text, _ in results), audio_seconds)
            return []
        return results

    @staticmethod
    def _segment_is_plausible(segment: object) -> bool:
        average_logprob = getattr(segment, "avg_logprob", None)
        return not (
            (average_logprob is not None and average_logprob < -1.2)
            or getattr(segment, "no_speech_prob", 0.0) > 0.65
            or getattr(segment, "compression_ratio", 0.0) > 2.4
        )

    def _vocabulary_prompt(self) -> str:
        if not self.vocabulary_file.exists():
            return ""
        names = [line.strip() for line in self.vocabulary_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
        return "Names and terms used in this D&D session: " + ", ".join(names[:100])
