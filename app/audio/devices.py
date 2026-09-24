"""Windows audio device discovery. Imports remain safe on non-Windows hosts."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioDevice:
    id: str
    name: str
    kind: str
    sample_rate: int


def list_microphones() -> list[AudioDevice]:
    try:
        import sounddevice as sd
        return [
            AudioDevice(str(index), info["name"], "microphone", int(info["default_samplerate"]))
            for index, info in enumerate(sd.query_devices()) if info["max_input_channels"] > 0
        ]
    except Exception:
        return []


def list_loopback_devices() -> list[AudioDevice]:
    try:
        import pyaudiowpatch as pyaudio
        audio = pyaudio.PyAudio()
        try:
            return [
                AudioDevice(str(info["index"]), info["name"], "system loopback", int(info["defaultSampleRate"]))
                for info in audio.get_loopback_device_info_generator()
            ]
        finally:
            audio.terminate()
    except Exception:
        return []


def describe_devices() -> list[AudioDevice]:
    return list_loopback_devices() + list_microphones()
