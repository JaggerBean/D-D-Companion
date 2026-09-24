from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import AudioConfig, DiscordConfig
from app.context.transcript_manager import SessionManager

try:
    import numpy as np
except ModuleNotFoundError:
    np = None


class FakeWorker:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, np.ndarray, int]] = []
        self.flushed: list[str] = []

    def submit_audio(self, source: str, samples: object, sample_rate: int) -> None:
        self.submissions.append((source, samples, sample_rate))

    def flush_source(self, source: str) -> None:
        self.flushed.append(source)


@unittest.skipUnless(np is not None, "numpy is installed by setup.bat")
class DiscordRouterTests(unittest.TestCase):
    def test_accepts_the_empty_starter_speaker_map(self) -> None:
        from app.discord_bot import DiscordAudioRouter
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            map_file = root / "speakers.yaml"
            map_file.write_text("speakers:\n", encoding="utf-8")
            session = SessionManager(root / "sessions")
            session.create_session("test")
            router = DiscordAudioRouter(DiscordConfig(speaker_map_file=str(map_file)), session, FakeWorker(), AudioConfig())
            self.assertEqual(router._speaker_map, {})
            router.close()
            session.close()

    def test_routes_known_member_to_character_and_archives_pcm(self) -> None:
        from app.discord_bot import DiscordAudioRouter
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            map_file = root / "speakers.yaml"
            map_file.write_text('speakers:\n  "42": "DM"\n', encoding="utf-8")
            session = SessionManager(root / "sessions")
            folder = session.create_session("test")
            worker = FakeWorker()
            audio = AudioConfig(utterance_silence_seconds=0.01)
            router = DiscordAudioRouter(DiscordConfig(speaker_map_file=str(map_file)), session, worker, audio)
            router.feed(42, "Discord Display", np.full((480, 2), 5000, dtype=np.int16).tobytes())
            router._flush_inactive(999999999.0)
            router.close()
            self.assertEqual(worker.submissions[0][0], "DM")
            self.assertEqual(worker.submissions[0][2], 48000)
            self.assertTrue(any((folder / "audio").glob("DM.wav")))
            session.close()
