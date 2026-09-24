"""Concurrent WASAPI loopback and microphone capture, each labelled at source."""
from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

from app.config import AudioConfig

LOGGER = logging.getLogger(__name__)
AudioCallback = Callable[[str, np.ndarray, int], None]


@dataclass
class CaptureStatus:
    system_running: bool = False
    microphone_running: bool = False
    last_error: str = ""


class AudioCapture:
    """Uses PyAudioWPatch for reliable WASAPI loopback; sounddevice for microphone."""

    def __init__(self, config: AudioConfig, on_audio: AudioCallback) -> None:
        self.config, self.on_audio = config, on_audio
        self.status = CaptureStatus()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._mic_stream = None

    def start(self) -> None:
        self._stop.clear()
        if self.config.capture_system_audio:
            self._start_thread("wasapi-loopback", self._system_worker)
        if self.config.capture_microphone:
            self._start_thread("microphone", self._microphone_worker)

    def _start_thread(self, name: str, target: Callable[[], None]) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        self._threads.append(thread)
        thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._mic_stream is not None:
            try:
                self._mic_stream.close()
            except Exception:
                pass
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()
        self.status.system_running = self.status.microphone_running = False

    def _system_worker(self) -> None:
        try:
            import pyaudiowpatch as pyaudio
            audio = pyaudio.PyAudio()
            device = self._loopback_device(audio)
            rate = int(device["defaultSampleRate"])
            channels = min(int(device["maxInputChannels"]), 2)
            frames = max(256, int(rate * self.config.chunk_seconds / 4))
            stream = audio.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                                input_device_index=device["index"], frames_per_buffer=frames)
            self.status.system_running = True
            LOGGER.info("System loopback started: %s", device["name"])
            while not self._stop.is_set():
                raw = stream.read(frames, exception_on_overflow=False)
                samples = np.frombuffer(raw, dtype=np.int16).reshape(-1, channels)
                self.on_audio("SESSION", samples, rate)
            stream.close()
            audio.terminate()
        except Exception as exc:
            self._failed("system audio", exc)
        finally:
            self.status.system_running = False

    def _loopback_device(self, audio: object) -> dict:
        if self.config.output_device != "auto":
            selected = int(self.config.output_device)
            for item in audio.get_loopback_device_info_generator():
                if item["index"] == selected:
                    return item
            raise RuntimeError(f"Selected loopback device {selected} unavailable")
        try:
            return audio.get_default_wasapi_loopback()
        except OSError:
            return next(audio.get_loopback_device_info_generator())

    def _microphone_worker(self) -> None:
        try:
            import sounddevice as sd
            device = None if self.config.microphone_device == "auto" else int(self.config.microphone_device)
            rate = self.config.sample_rate
            frames = max(256, int(rate * self.config.chunk_seconds / 4))
            def callback(indata: np.ndarray, frame_count: int, time: object, status: object) -> None:
                if status:
                    LOGGER.warning("Microphone status: %s", status)
                self.on_audio("ME", indata.copy(), rate)
            with sd.InputStream(device=device, samplerate=rate, channels=1, dtype="int16", blocksize=frames, callback=callback) as stream:
                self._mic_stream = stream
                self.status.microphone_running = True
                LOGGER.info("Microphone capture started")
                while not self._stop.wait(0.1):
                    pass
        except Exception as exc:
            self._failed("microphone", exc)
        finally:
            self.status.microphone_running = False
            self._mic_stream = None

    def _failed(self, label: str, exc: Exception) -> None:
        self.status.last_error = f"{label}: {exc}"
        LOGGER.exception("%s capture failed", label)
