from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import AppConfig, load_config, save_config
from app.context.notes_manager import NotesManager
from app.context.prompt_builder import PromptBuilder
from app.context.transcript_manager import SessionManager
from app.models.transcript_entry import TranscriptEntry


class ContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = SessionManager(self.root / "sessions")
        self.session.create_session("test")
        self.config = AppConfig()
        self.config.context.recent_seconds = 90

    def tearDown(self) -> None:
        self.session.close()
        self.temp.cleanup()

    def test_prompt_uses_recent_entries_notes_and_mode(self) -> None:
        self.session.add_entry(TranscriptEntry.spoken("SESSION", "Tamsin knows the Viper."))
        self.session.add_entry(TranscriptEntry.spoken("ME", "What do you know?"))
        self.session.add_note("Tamsin Rook survived.")
        prompt = PromptBuilder(self.session, self.config, self.root / "character").build("roleplay")
        self.assertIn("Tamsin knows the Viper.", prompt)
        self.assertIn("Tamsin Rook survived.", prompt)
        self.assertIn("Respond in character.", prompt)

    def test_scene_marker_excludes_older_context(self) -> None:
        self.session.add_entry(TranscriptEntry.spoken("SESSION", "Old scene."))
        self.session.add_entry(TranscriptEntry.scene())
        self.session.add_entry(TranscriptEntry.spoken("SESSION", "New scene."))
        recent = self.session.recent(90)
        self.assertEqual([entry.text for entry in recent], ["New scene."])

    def test_prompt_keeps_current_scene_beyond_the_old_time_window(self) -> None:
        self.session.add_entry(TranscriptEntry.spoken("SESSION", "Earlier in this same scene."))
        self.session.add_entry(TranscriptEntry.spoken("ME", "The current decision depends on that."))
        prompt = PromptBuilder(self.session, self.config, self.root / "character").build("tactics")
        self.assertIn("Earlier in this same scene.", prompt)
        self.assertIn("The current decision depends on that.", prompt)

    def test_mark_important_persists_recent_dialogue(self) -> None:
        self.session.add_entry(TranscriptEntry.spoken("ME", "Ask about Undertow."))
        marked = NotesManager(self.session).mark_recent(30)
        self.assertIn("Ask about Undertow.", marked)
        self.assertIn("Ask about Undertow.", self.session.notes())

    def test_session_reopens_from_jsonl(self) -> None:
        self.session.add_entry(TranscriptEntry.spoken("SESSION", "Persist me."))
        folder = self.session.session_dir
        assert folder
        second = SessionManager(self.root / "sessions")
        second.resume_session(folder)
        self.assertEqual(second.latest(90)[-1].text, "Persist me.")
        second.close()

    def test_session_can_be_renamed_with_date_only_folder(self) -> None:
        renamed = self.session.rename_session("Sunken Archive")
        self.assertRegex(renamed.name, r"^\d{4}-\d{2}-\d{2}_Sunken Archive$")
        self.assertEqual(self.session.session_name, "Sunken Archive")

    def test_event_marker_is_unambiguous_in_transcript(self) -> None:
        marker = TranscriptEntry.event("NPC", "Captain Veyra", "Met at Blackwater Inn")
        self.assertIn("[DND_EVENT_START]", marker.display())
        self.assertIn("TYPE: NPC", marker.display())
        self.assertIn("[DND_EVENT_END]", marker.display())

    def test_user_correction_rewrites_transcript(self) -> None:
        self.session.add_entry(TranscriptEntry.spoken("SESSION", "Wrong dragon name."))
        self.session.update_entry(0, "Correct dragon name.")
        self.assertEqual(self.session.all_entries()[0].text, "Correct dragon name.")
        assert self.session.session_dir
        self.assertIn("Correct dragon name.", (self.session.session_dir / "transcript.txt").read_text(encoding="utf-8"))

    def test_config_round_trip(self) -> None:
        path = self.root / "config.yaml"
        self.config.hotkeys.roleplay = "ctrl+alt+r"
        save_config(self.config, path)
        self.assertEqual(load_config(path).hotkeys.roleplay, "ctrl+alt+r")

    def test_discord_config_round_trip(self) -> None:
        path = self.root / "config.yaml"
        self.config.discord.application_guild_id = "123456789"
        self.config.discord.controller_user_ids = ["111"]
        save_config(self.config, path)
        loaded = load_config(path)
        self.assertEqual(loaded.discord.application_guild_id, "123456789")
        self.assertEqual(loaded.discord.controller_user_ids, ["111"])
