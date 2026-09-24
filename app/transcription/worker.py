"""Non-blocking audio aggregation and background local transcription."""
from __future__ import annotations

import logging
import queue
import re
import threading
import time
from collections import defaultdict
from typing import Callable

import numpy as np

from app.config import AppConfig
from app.models.transcript_entry import TranscriptEntry
from app.transcription.whisper_engine import WhisperEngine

LOGGER = logging.getLogger(__name__)


class TranscriptionWorker:
    def __init__(self, config: AppConfig, engine: WhisperEngine, on_entry: Callable[[TranscriptEntry], None]) -> None:
        self.config, self.engine, self.on_entry = config, engine, on_entry
        self._chunks: queue.Queue[tuple[str, str, np.ndarray | None, int | None]] = queue.Queue(maxsize=160)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.running = False
        self.last_error = ""
        self._last_queue_warning = 0.0
        self._recent_words: dict[str, list[str]] = defaultdict(list)

    def submit_audio(self, source: str, samples: np.ndarray, sample_rate: int) -> None:
        try:
            self._chunks.put_nowait(("audio", source, samples, sample_rate))
        except queue.Full:
            try:
                self._chunks.get_nowait()
                self._chunks.put_nowait(("audio", source, samples, sample_rate))
                now = time.monotonic()
                if now - self._last_queue_warning >= 5:
                    LOGGER.warning("Audio queue full; dropping stale audio until transcription catches up")
                    self._last_queue_warning = now
            except queue.Empty:
                pass

    def flush_source(self, source: str) -> None:
        """Transcribe a short final utterance after Discord reports silence."""
        try:
            self._chunks.put_nowait(("flush", source, None, None))
        except queue.Full:
            LOGGER.warning("Audio queue full; could not flush %s", source)

    def start(self) -> None:
        if self.running or (self._thread is not None and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="transcription", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._thread = None
        self.running = False

    def _run(self) -> None:
        try:
            self.engine.load()
            self.running = True
            while not self._stop.is_set():
                try:
                    kind, source, samples, rate = self._chunks.get(timeout=0.2)
                except queue.Empty:
                    continue
                if kind == "flush":
                    # Kept for compatibility with old capture callers. Discord
                    # now submits complete speaker utterances directly.
                    continue
                assert samples is not None and rate is not None
                self._transcribe(source, samples, rate)
        except Exception as exc:
            self.last_error = str(exc)
            LOGGER.exception("Transcription worker stopped")
        finally:
            self.running = False

    def _transcribe(self, source: str, samples: np.ndarray, sample_rate: int) -> None:
        audio = self._to_whisper_audio(samples, sample_rate)
        if not self._has_speech(audio):
            return
        for text, confidence in self.engine.transcribe(audio):
            clean = self._clean(text)
            clean = self._trim_overlap(source, clean)
            if clean:
                self.on_entry(TranscriptEntry.spoken(source, clean, confidence))

    def _trim_overlap(self, source: str, text: str) -> str:
        """Remove words repeated only because adjacent audio windows overlap."""
        words = text.split()
        normalized = [self._normalize_word(word) for word in words]
        history = self._recent_words[source]
        max_overlap = min(14, len(history), len(normalized))
        trim = 0
        for size in range(max_overlap, 1, -1):
            if history[-size:] == normalized[:size]:
                trim = size
                break
        remaining_words = words[trim:]
        remaining_normalized = normalized[trim:]
        if remaining_normalized:
            self._recent_words[source] = (history + remaining_normalized)[-24:]
        return " ".join(remaining_words)

    @staticmethod
    def _normalize_word(word: str) -> str:
        return re.sub(r"[^a-z0-9']", "", word.lower())

    @staticmethod
    def _to_whisper_audio(samples: np.ndarray, sample_rate: int) -> np.ndarray:
        audio = samples.astype(np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if samples.dtype == np.int16:
            audio /= 32768.0
        if sample_rate == 16000:
            return audio
        output_length = max(1, round(len(audio) * 16000 / sample_rate))
        return np.interp(np.linspace(0, len(audio) - 1, output_length), np.arange(len(audio)), audio).astype(np.float32)

    def _has_speech(self, audio: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
        db = 20 * np.log10(max(rms, 1e-9))
        return db >= self.config.audio.speech_threshold_db

    @staticmethod
    def _clean(text: str) -> str:
        text = " ".join(text.split())
        # Avoid obvious repeated hallucination only; never rewrite dialogue.
        halves = len(text) // 2
        if halves and text[:halves].strip().lower() == text[halves:].strip().lower():
            return text[:halves].strip()
        return text
