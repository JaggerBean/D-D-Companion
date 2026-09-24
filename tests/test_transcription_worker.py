from __future__ import annotations

from app.config import AppConfig
from app.transcription.worker import TranscriptionWorker


class _Engine:
    def load(self) -> None:
        pass

    def transcribe(self, audio):
        return []


def test_overlap_words_are_not_emitted_twice() -> None:
    worker = TranscriptionWorker(AppConfig(), _Engine(), lambda entry: None)
    assert worker._trim_overlap("DM", "We need to open") == "We need to open"
    assert worker._trim_overlap("DM", "to open the door") == "the door"


def test_short_repeated_phrase_is_preserved() -> None:
    worker = TranscriptionWorker(AppConfig(), _Engine(), lambda entry: None)
    assert worker._trim_overlap("DM", "yes") == "yes"
    assert worker._trim_overlap("DM", "yes") == "yes"
