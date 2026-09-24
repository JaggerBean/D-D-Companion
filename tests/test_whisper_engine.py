from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from app.config import WhisperConfig
from app.transcription.whisper_engine import WhisperEngine


class _Segment:
    text = "fallback works"
    avg_logprob = -0.1


class _FakeWhisperModel:
    created_devices: list[str] = []

    def __init__(self, model: str, device: str, compute_type: str) -> None:
        self.device = device
        self.created_devices.append(device)

    def transcribe(self, audio: np.ndarray, **kwargs: object):
        if self.device == "cuda":
            def failing_segments():
                raise RuntimeError("cublas64_12.dll is not found")
                yield
            return failing_segments(), None
        return iter([_Segment()]), None


class WhisperEngineTests(unittest.TestCase):
    def test_cuda_inference_failure_retries_on_cpu(self) -> None:
        fake_module = types.SimpleNamespace(WhisperModel=_FakeWhisperModel)
        _FakeWhisperModel.created_devices.clear()
        engine = WhisperEngine(WhisperConfig(), Path("missing-vocabulary.txt"))
        with patch.object(engine, "_prepare_cuda_runtime"), patch.dict(sys.modules, {"faster_whisper": fake_module}):
            engine.load()
            result = engine.transcribe(np.zeros(16000, dtype=np.float32))
        self.assertEqual(_FakeWhisperModel.created_devices, ["cuda", "cpu"])
        self.assertEqual(engine.active_device, "cpu (CUDA fallback)")
        self.assertEqual(result[0][0], "fallback works")
