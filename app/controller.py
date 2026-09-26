"""Coordinates local capture, local transcription, persistence and handoff."""
from __future__ import annotations

import logging
import os
import ctypes
import textwrap
import base64
import re
import threading
from uuid import uuid4
from pathlib import Path

from app.config import AppConfig, CampaignConfig, ROOT, resolve_character_dir, save_config
from app.context.notes_manager import NotesManager
from app.context.transcript_manager import SessionManager
from app.hotkeys.hotkey_manager import HotkeyManager
from app.models.transcript_entry import TranscriptEntry
from app.transcription.whisper_engine import WhisperEngine
from app.transcription.worker import TranscriptionWorker
from app.update_manager import UpdateManager

LOGGER = logging.getLogger(__name__)
WHISPER_MODELS = ("large-v3-turbo", "distil-large-v3", "medium", "small")


class AppController:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.session = SessionManager(self._campaign_sessions_root())
        self.notes = NotesManager(self.session)
        self.engine = WhisperEngine(config.whisper, ROOT / "config" / "vocabulary.txt")
        # Move the former app-wide vocabulary into the migrated default
        # campaign once, so old names are retained without bleeding into other
        # campaigns.
        campaign = self._campaign()
        legacy_vocabulary = ROOT / "config" / "vocabulary.txt"
        if campaign.id == "default" and not campaign.vocabulary and legacy_vocabulary.exists():
            campaign.vocabulary = legacy_vocabulary.read_text(encoding="utf-8").strip()
            if campaign.vocabulary:
                save_config(self.config)
        self.engine.vocabulary_text = self._campaign().vocabulary
        self.worker = TranscriptionWorker(config, self.engine, self._on_entry)
        self.hotkeys = HotkeyManager(config.hotkeys, self._run_shortcut)
        self.updates = UpdateManager()
        self._window_callback = None
        self._capture_menu_callback = None
        self._scene_menu_callback = None
        self._active_scene: dict[str, str] | None = None
        self.last_handoff = ""
        self.discord_router = None
        self.discord_bot = None
        self.relay_subscriber = None
        self._participants_lock = threading.RLock()
        self._voice_members: dict[str, dict[str, str]] = {}

    @property
    def is_listening(self) -> bool:
        return self.worker.running

    def active_scene(self) -> dict[str, str] | None:
        return dict(self._active_scene) if self._active_scene else None

    def _campaign(self) -> CampaignConfig:
        for campaign in self.config.campaigns:
            if campaign.id == self.config.active_campaign_id:
                return campaign
        self.config.active_campaign_id = self.config.campaigns[0].id
        return self.config.campaigns[0]

    def _campaign_sessions_root(self) -> Path:
        campaign = self._campaign()
        # Existing installs retain their historical session folder; every new
        # campaign gets an isolated subfolder and its own session database.
        if campaign.id == "default":
            return ROOT / "sessions"
        return ROOT / "sessions" / campaign.id

    def campaigns(self) -> list[dict[str, object]]:
        return [
            {
                "id": campaign.id,
                "name": campaign.name,
                "icon": self._participant_icon_uri(campaign.icon),
                "vault_directory": campaign.vault_directory,
                "active": campaign.id == self.config.active_campaign_id,
            }
            for campaign in self.config.campaigns
        ]

    def create_campaign(self, name: str) -> CampaignConfig:
        if self.is_listening:
            raise RuntimeError("Stop the listener before creating a campaign")
        cleaned = " ".join(name.split())
        if not cleaned:
            raise ValueError("Give the campaign a name")
        if len(cleaned) > 100:
            raise ValueError("Campaign names must be 100 characters or fewer")
        campaign = CampaignConfig(name=cleaned)
        self.config.campaigns.append(campaign)
        self.config.active_campaign_id = campaign.id
        self._active_scene = None
        self.session = SessionManager(self._campaign_sessions_root())
        self.notes = NotesManager(self.session)
        self.engine.vocabulary_text = campaign.vocabulary
        save_config(self.config)
        return campaign

    def update_campaign_icon(self, icon_data: str = "", clear_icon: bool = False) -> None:
        campaign = self._campaign()
        if clear_icon:
            campaign.icon = ""
        if icon_data:
            campaign.icon = self._save_campaign_icon(icon_data)
        save_config(self.config)

    def rename_campaign(self, name: str) -> None:
        cleaned = " ".join(name.split())
        if not cleaned:
            raise ValueError("Give the campaign a name")
        if len(cleaned) > 100:
            raise ValueError("Campaign names must be 100 characters or fewer")
        self._campaign().name = cleaned
        save_config(self.config)

    def switch_campaign(self, campaign_id: str) -> None:
        if self.is_listening:
            raise RuntimeError("Stop the listener before switching campaigns")
        campaign_id = campaign_id.strip()
        if campaign_id not in {campaign.id for campaign in self.config.campaigns}:
            raise ValueError("That campaign is no longer available")
        if campaign_id == self.config.active_campaign_id:
            return
        self.config.active_campaign_id = campaign_id
        self._active_scene = None
        self.session = SessionManager(self._campaign_sessions_root())
        self.notes = NotesManager(self.session)
        self.engine.vocabulary_text = self._campaign().vocabulary
        save_config(self.config)

    def update_campaign_vocabulary(self, vocabulary: str) -> None:
        if len(vocabulary) > 12_000:
            raise ValueError("Keep campaign vocabulary under 12,000 characters")
        self._campaign().vocabulary = vocabulary.strip()
        self.engine.vocabulary_text = self._campaign().vocabulary
        save_config(self.config)

    def update_campaign_ai_context(self, context: str) -> None:
        if len(context) > 24_000:
            raise ValueError("Keep campaign context under 24,000 characters")
        self._campaign().ai_context = context.strip()
        save_config(self.config)

    def set_show_window_callback(self, callback: object) -> None:
        self._window_callback = callback

    def set_capture_menu_callback(self, callback: object) -> None:
        self._capture_menu_callback = callback

    def set_scene_menu_callback(self, callback: object) -> None:
        self._scene_menu_callback = callback

    def update_shortcuts(self, shortcuts: object) -> None:
        if not isinstance(shortcuts, list):
            raise ValueError("Shortcut settings could not be read.")
        allowed_actions = {"event", "scene", "listener"}
        allowed_event_types = {"NPC", "Lore", "Location", "Item", "Quest / Lead", "Faction", "Other"}
        cleaned: list[dict[str, object]] = []
        used_keys: set[str] = set()
        for raw in shortcuts[:24]:
            if not isinstance(raw, dict):
                continue
            action = str(raw.get("action", "event")).strip().lower()
            if action not in allowed_actions:
                raise ValueError("Choose Event, Scene, or Listener for every shortcut.")
            keys = str(raw.get("keys", "")).strip().lower()
            enabled = bool(raw.get("enabled", True))
            if enabled and not keys:
                raise ValueError("Every enabled shortcut needs a key combination.")
            if enabled and keys in used_keys:
                raise ValueError("Each enabled shortcut must use a different key combination.")
            used_keys.add(keys)
            event_type = str(raw.get("event_type", "Other")).strip()
            if action == "event" and event_type not in allowed_event_types:
                event_type = "Other"
            scene_label = " ".join(str(raw.get("scene_label", "")).split())[:120]
            if action != "scene":
                scene_label = ""
            cleaned.append({
                "id": str(raw.get("id", "")).strip() or uuid4().hex,
                "action": action,
                "event_type": event_type if action == "event" else "",
                "keys": keys,
                "enabled": enabled,
                "scene_label": scene_label,
            })
        was_registered = self.hotkeys.running
        if was_registered:
            self.hotkeys.stop()
        self.config.hotkeys.shortcuts = cleaned
        save_config(self.config)
        if was_registered:
            self.hotkeys.start()

    def _run_shortcut(self, shortcut: dict[str, object]) -> None:
        action = str(shortcut.get("action", ""))
        if action == "event":
            self.open_capture_menu(str(shortcut.get("event_type", "Other")))
        elif action == "scene":
            shortcut_id = str(shortcut.get("id", ""))
            if self._active_scene and self._active_scene.get("shortcut_id") == shortcut_id:
                self.end_scene()
                return
            label = str(shortcut.get("scene_label", "")).strip()
            if not label:
                self.open_scene_menu(shortcut_id)
            else:
                self.new_scene(label, shortcut_id)
        elif action == "listener":
            if self.is_listening:
                self.stop_listening()
            else:
                self.start_listening()

    def update_whisper_model(self, model: str) -> None:
        if model not in WHISPER_MODELS:
            raise ValueError("Choose one of the available Whisper models")
        self.config.whisper.model = model
        save_config(self.config)

    def create_session(self, name: str) -> Path:
        self._active_scene = None
        return self.session.create_session(name)

    def rename_session(self, name: str) -> Path:
        if self.discord_router is not None:
            self.discord_router.release_archives()
        return self.session.rename_session(name)

    def set_vault_directory(self, directory: str) -> None:
        path = Path(directory).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("Choose an existing Obsidian vault folder")
        self._campaign().vault_directory = str(path)
        save_config(self.config)

    def create_vault_directory(self, parent_directory: str, name: str) -> Path:
        """Create a conservative, local-only starter structure for a new vault."""
        parent = Path(parent_directory).expanduser().resolve()
        cleaned_name = " ".join(name.split())
        if not parent.is_dir():
            raise ValueError("Choose a folder where the new vault should be created")
        if not cleaned_name:
            raise ValueError("Give the new vault a name")
        if any(character in cleaned_name for character in '<>:"/\\|?*'):
            raise ValueError("The vault name contains characters Windows cannot use")
        vault = parent / cleaned_name
        if vault.exists():
            raise ValueError("A folder with that vault name already exists. Choose another name or select it as an existing vault.")
        try:
            vault.mkdir()
            for folder in (
                "Sessions",
                "People",
                "Locations",
                "Factions",
                "Lore",
                "Items",
                "Quests",
                "Images",
            ):
                (vault / folder).mkdir()
            (vault / "README.md").write_text(
                "# " + cleaned_name + "\n\n"
                "This vault was created by D&D Companion. Session notes and canonical campaign material can live here.\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise RuntimeError(f"Could not create the vault: {exc}") from exc
        self._campaign().vault_directory = str(vault)
        save_config(self.config)
        return vault

    def update_ai_instructions(self, instructions: str) -> None:
        cleaned = instructions.strip()
        if not cleaned:
            raise ValueError("AI instructions cannot be empty")
        if len(cleaned) > 24_000:
            raise ValueError("Keep AI instructions under 24,000 characters")
        self.config.ai.instructions = cleaned
        save_config(self.config)

    def check_for_updates(self) -> dict[str, object]:
        return self.updates.check()

    def check_for_updates_async(self) -> None:
        self.updates.check_async()

    def install_update(self) -> dict[str, object]:
        return self.updates.install()

    def start_listening(self) -> None:
        self._ensure_session()
        try:
            self.worker.start()
            self.hotkeys.start()
            if self.relay_subscriber is None:
                from app.relay.subscriber import RelaySubscriber
                self.relay_subscriber = RelaySubscriber(
                    self.config.relay.endpoint,
                    self.config.relay.room,
                    self.config.relay.token_file,
                    self._on_relay_audio,
                    self._on_relay_members,
                )
            self.relay_subscriber.start()
            LOGGER.info("Relay listener started")
        except Exception:
            self.stop_listening()
            raise

    def start_discord_bot(self) -> None:
        """Start Discord's separate-member receiver instead of desktop loopback."""
        self._ensure_session()
        try:
            self.worker.start()
            self.hotkeys.start()
            if self.discord_router is None:
                from app.discord_bot import DiscordAudioRouter, DiscordVoiceBot
                self.discord_router = DiscordAudioRouter(self.config.discord, self.session, self.worker, self.config.audio)
                self.discord_bot = DiscordVoiceBot(self.config.discord, self.discord_router)
            self.discord_bot.start()
            LOGGER.info("Discord bot started")
        except Exception:
            self.stop_listening()
            raise

    def stop_listening(self) -> None:
        if self.relay_subscriber is not None:
            self.relay_subscriber.stop()
            self.relay_subscriber = None
        if self.discord_bot is not None:
            self.discord_bot.stop()
            self.discord_bot = None
        if self.discord_router is not None:
            self.discord_router.close()
            self.discord_router = None
        self.worker.stop()
        LOGGER.info("Listening stopped")

    def _on_entry(self, entry: TranscriptEntry) -> None:
        try:
            self.session.add_entry(entry)
        except Exception:
            LOGGER.exception("Could not save transcript entry")

    def _on_relay_members(self, members: list[dict[str, str]]) -> None:
        changed = False
        with self._participants_lock:
            self._voice_members = {}
            for member in members:
                member_id, name = member.get("id", ""), member.get("name", "")
                if not member_id or not name:
                    continue
                self._voice_members[member_id] = {
                    "id": member_id,
                    "name": name,
                    "avatar": member.get("avatar", ""),
                }
                if member_id not in self._campaign().participants:
                    self._campaign().participants[member_id] = {"nickname": "", "enabled": True, "icon": ""}
                    changed = True
        if changed:
            save_config(self.config)

    def _on_relay_audio(self, member_id: str, name: str, samples: object, sample_rate: int) -> None:
        """Apply local member preferences before audio reaches the transcription queue."""
        member_id = member_id.strip() or name.strip() or "unknown"
        name = name.strip() or member_id
        changed = False
        with self._participants_lock:
            current = self._voice_members.get(member_id, {"id": member_id, "name": name, "avatar": ""})
            current["name"] = name
            self._voice_members[member_id] = current
            profile = self._campaign().participants.get(member_id)
            if not isinstance(profile, dict):
                profile = {"nickname": "", "enabled": True, "icon": ""}
                self._campaign().participants[member_id] = profile
                changed = True
            enabled = bool(profile.get("enabled", True))
            source = str(profile.get("nickname", "")).strip() or name
        if changed:
            save_config(self.config)
        if enabled:
            self.worker.submit_audio(source, samples, sample_rate)  # type: ignore[arg-type]

    def participants(self) -> list[dict[str, object]]:
        with self._participants_lock:
            members = list(self._voice_members.values())
            profiles = dict(self._campaign().participants)
        # Before the first roster packet arrives, keep speakers who have already
        # talked visible so their settings remain reachable.
        if not members:
            members = [{"id": member_id, "name": member_id, "avatar": ""} for member_id in profiles]
        result: list[dict[str, object]] = []
        for member in members:
            member_id = member["id"]
            profile = profiles.get(member_id, {})
            icon = self._participant_icon_uri(str(profile.get("icon", "")))
            result.append({
                "id": member_id,
                "name": member["name"],
                "nickname": str(profile.get("nickname", "")),
                "enabled": bool(profile.get("enabled", True)),
                "avatar": icon or member.get("avatar", ""),
            })
        return sorted(result, key=lambda item: str(item["nickname"] or item["name"]).lower())

    def update_participant(self, member_id: str, nickname: str, enabled: bool, icon_data: str = "", clear_icon: bool = False) -> int:
        cleaned_id = member_id.strip()
        if not cleaned_id:
            raise ValueError("That participant is no longer available")
        cleaned_name = " ".join(nickname.split())
        if len(cleaned_name) > 80:
            raise ValueError("Nicknames must be 80 characters or fewer")
        with self._participants_lock:
            profile = self._campaign().participants.setdefault(cleaned_id, {"nickname": "", "enabled": True, "icon": ""})
            previous_nickname = str(profile.get("nickname", "")).strip()
            member_name = str(self._voice_members.get(cleaned_id, {}).get("name", "")).strip()
            profile["nickname"] = cleaned_name
            profile["enabled"] = bool(enabled)
            if clear_icon:
                profile["icon"] = ""
            if icon_data:
                profile["icon"] = self._save_participant_icon(cleaned_id, icon_data)
        save_config(self.config)
        display_name = cleaned_name or member_name or previous_nickname
        return self.session.rename_source({previous_nickname, member_name}, display_name)

    @staticmethod
    def _participant_icon_uri(relative_path: str) -> str:
        if not relative_path:
            return ""
        path = ROOT / relative_path
        return path.resolve().as_uri() if path.is_file() else ""

    def _save_participant_icon(self, member_id: str, data_url: str) -> str:
        try:
            header, encoded = data_url.split(",", 1)
            mime = header[5:].split(";", 1)[0].lower()
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError):
            raise ValueError("That profile image could not be read") from None
        suffixes = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
        if mime not in suffixes or not data or len(data) > 2 * 1024 * 1024:
            raise ValueError("Use a PNG, JPG, WebP, or GIF image smaller than 2 MB")
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", member_id)[:80] or "participant"
        folder = ROOT / "config" / "participant-icons" / self._campaign().id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{safe_id}{suffixes[mime]}"
        path.write_bytes(data)
        return str(path.relative_to(ROOT)).replace("\\", "/")

    def _save_campaign_icon(self, data_url: str) -> str:
        try:
            header, encoded = data_url.split(",", 1)
            mime = header[5:].split(";", 1)[0].lower()
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError):
            raise ValueError("That campaign image could not be read") from None
        suffixes = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
        if mime not in suffixes or not data or len(data) > 2 * 1024 * 1024:
            raise ValueError("Use a PNG, JPG, WebP, or GIF image smaller than 2 MB")
        folder = ROOT / "config" / "campaign-icons"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self._campaign().id}{suffixes[mime]}"
        path.write_bytes(data)
        return str(path.relative_to(ROOT)).replace("\\", "/")

    def mark_important(self) -> str:
        marked = self.notes.mark_recent(self.config.context.important_note_seconds)
        self.last_handoff = "Recent transcript saved to notes" if marked else "No recent transcript to mark"
        self._notify()
        return marked

    def add_note(self, text: str) -> None:
        self._ensure_session()
        self.notes.add_manual(text)
        self.last_handoff = "Note saved"

    def new_scene(self, label: str = "", shortcut_id: str = "") -> None:
        self._ensure_session()
        if self._active_scene:
            self._end_active_scene()
        cleaned_label = " ".join(label.split())
        scene_id = uuid4().hex
        self.session.add_entry(TranscriptEntry.scene(cleaned_label, "start", scene_id))
        self._active_scene = {"id": scene_id, "label": cleaned_label, "shortcut_id": shortcut_id}
        self.last_handoff = "Scene started" + (f": {cleaned_label}" if cleaned_label else "")
        self._notify()

    def end_scene(self) -> None:
        if not self._active_scene:
            self.last_handoff = "No active scene to end"
            return
        self._end_active_scene()
        self._notify()

    def _end_active_scene(self) -> None:
        if not self._active_scene:
            return
        self.session.add_entry(TranscriptEntry.scene(
            self._active_scene["label"],
            "end",
            self._active_scene["id"],
        ))
        self.last_handoff = "Scene ended" + (f": {self._active_scene['label']}" if self._active_scene["label"] else "")
        self._active_scene = None

    def add_event_marker(
        self,
        event_type: str,
        label: str = "",
        details: str = "",
        image_data: str = "",
        image_name: str = "",
        after_index: int | None = None,
    ) -> None:
        self._ensure_session()
        image_path = self.session.save_event_image(image_data, image_name) if image_data else ""
        entry = TranscriptEntry.event(event_type, label, details, image_path)
        if after_index is None:
            self.session.add_entry(entry)
            self.last_handoff = f"{event_type.title()} marker added"
        else:
            self.session.insert_entry_after(int(after_index), entry)
            self.last_handoff = f"{event_type.title()} marker inserted after transcript entry"
        self._notify()

    def update_transcript_entry(self, index: int, text: str) -> None:
        self.session.update_entry(index, text)
        self.last_handoff = "Transcript entry updated"
        self._notify()

    def open_capture_menu(self, event_type: str = "") -> None:
        self.show_window()
        if callable(self._capture_menu_callback):
            self._capture_menu_callback(event_type)

    def open_scene_menu(self, shortcut_id: str = "") -> None:
        self.show_window()
        if callable(self._scene_menu_callback):
            self._scene_menu_callback(shortcut_id)

    def show_window(self) -> None:
        if callable(self._window_callback):
            self._window_callback()

    def open_session_folder(self) -> None:
        self._ensure_session()
        assert self.session.session_dir is not None
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(self.session.session_dir))
            else:
                LOGGER.info("Session folder: %s", self.session.session_dir)
        except OSError as exc:
            raise RuntimeError(f"Could not open the session folder: {exc}") from exc

    def session_processing_prompt(self) -> str:
        """Build a self-contained prompt that can be pasted directly into ChatGPT."""
        self._ensure_session()
        assert self.session.session_dir is not None
        session_dir = self.session.session_dir
        transcript_path = session_dir / "transcript.jsonl"
        notes_path = session_dir / "notes.md"
        transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
        notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
        images = sorted((session_dir / "images").glob("*")) if (session_dir / "images").exists() else []
        image_list = "\n".join(f"- {image}" for image in images) or "- No event images were attached."
        vault_directory = self._campaign().vault_directory or "[No Obsidian vault folder has been selected yet.]"
        return textwrap.dedent(
            f"""\
            # D&D Session → Obsidian Vault Processing Request

            Process this D&D session conservatively and produce Obsidian-ready updates.

            ## Source files
            These are the local source paths for reference. The transcript and notes are included below so you can work from this pasted prompt.
            - Session folder: {session_dir}
            - Structured transcript (JSON Lines): {transcript_path}
            - Session notes: {notes_path}
            - Event-image folder: {session_dir / 'images'}

            ## Obsidian vault destination
            Place the proposed Markdown files and edits in this vault:
            {vault_directory}
            If no vault folder is configured, ask me to select one before giving final file paths.

            ## Campaign-specific context
            {self._campaign().ai_context or '[No campaign-specific context has been added yet.]'}

            Event images saved for this session:
            {image_list}

            ## How to read the structured transcript
            The transcript below is JSON Lines: one chronological JSON object per entry.
            - Ordinary dialogue has `source`, `text`, `timestamp`, and sometimes `confidence`.
            - A scene boundary has `scene_marker: true`, `marker_type: "scene"`, an ID in `scene_id`, and a lifecycle value in `scene_state` (`start` or `end`). Its optional label is in `label`.
            - An explicit user event capture has `event_marker: true`, `marker_type: "event"`, `captured_by_user: true`, and dedicated `event_type`, `label`, `details`, `image_path`, and `canon_permission` fields.
            - Use timestamps and the adjacent dialogue entries to understand the context around each marked entry.

            {self.config.ai.instructions}

            ## STRUCTURED TRANSCRIPT (JSONL)
            {transcript or '[No transcript has been recorded yet.]'}

            ## IMPORTANT SESSION NOTES
            {notes or '[No manual notes were saved.]'}
            """
        ).strip()

    def copy_session_processing_prompt(self) -> None:
        prompt = self.session_processing_prompt()
        if os.name != "nt":
            raise RuntimeError("Clipboard copying is available in the Windows desktop app only")
        # Use the native Windows clipboard so large transcripts do not hit shell command-length limits.
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.OpenClipboard.argtypes, user32.OpenClipboard.restype = [wintypes.HWND], wintypes.BOOL
        user32.EmptyClipboard.argtypes, user32.EmptyClipboard.restype = [], wintypes.BOOL
        user32.SetClipboardData.argtypes, user32.SetClipboardData.restype = [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE
        user32.CloseClipboard.argtypes, user32.CloseClipboard.restype = [], wintypes.BOOL
        kernel32.GlobalAlloc.argtypes, kernel32.GlobalAlloc.restype = [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes, kernel32.GlobalLock.restype = [wintypes.HGLOBAL], ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes, kernel32.GlobalUnlock.restype = [wintypes.HGLOBAL], wintypes.BOOL
        kernel32.GlobalFree.argtypes, kernel32.GlobalFree.restype = [wintypes.HGLOBAL], wintypes.HGLOBAL
        if not user32.OpenClipboard(None):
            raise RuntimeError("Could not open the clipboard. Try again in a moment.")
        handle = None
        try:
            if not user32.EmptyClipboard():
                raise RuntimeError("Could not clear the clipboard. Try again in a moment.")
            handle = kernel32.GlobalAlloc(0x0002, (len(prompt) + 1) * ctypes.sizeof(ctypes.c_wchar))
            if not handle:
                raise RuntimeError("Could not allocate clipboard memory")
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise RuntimeError("Could not write to the clipboard")
            try:
                ctypes.memmove(pointer, ctypes.create_unicode_buffer(prompt), (len(prompt) + 1) * ctypes.sizeof(ctypes.c_wchar))
            finally:
                kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT; clipboard owns handle after success.
                raise RuntimeError("Could not write to the clipboard")
            handle = None
        finally:
            if handle:
                kernel32.GlobalFree(handle)
            user32.CloseClipboard()

    def status(self) -> dict[str, str]:
        return {
            "model": f"{self.config.whisper.model} ({self.engine.active_device})",
            "session": self.session.session_name or "D&D Session",
            "recording": "LISTENING" if self.is_listening else "stopped",
            "discord": self.relay_subscriber.status if self.relay_subscriber else "stopped",
            "error": self.worker.last_error or (self.relay_subscriber.last_error if self.relay_subscriber else ""),
        }

    def _notify(self) -> None:
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            pass

    def _ensure_session(self) -> None:
        if not self.session.session_dir:
            self.create_session("D&D Session")

    def shutdown(self) -> None:
        self.stop_listening()
        self.hotkeys.stop()
        self.session.close()
