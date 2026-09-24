"""Coordinates local capture, local transcription, persistence and handoff."""
from __future__ import annotations

import logging
import os
import ctypes
import textwrap
from pathlib import Path

from app.config import AppConfig, ROOT, resolve_character_dir, save_config
from app.context.notes_manager import NotesManager
from app.context.transcript_manager import SessionManager
from app.hotkeys.hotkey_manager import HotkeyManager
from app.models.transcript_entry import TranscriptEntry
from app.transcription.whisper_engine import WhisperEngine
from app.transcription.worker import TranscriptionWorker

LOGGER = logging.getLogger(__name__)
WHISPER_MODELS = ("large-v3-turbo", "distil-large-v3", "medium", "small")


class AppController:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.session = SessionManager(ROOT / "sessions")
        self.notes = NotesManager(self.session)
        self.engine = WhisperEngine(config.whisper, ROOT / "config" / "vocabulary.txt")
        self.worker = TranscriptionWorker(config, self.engine, self._on_entry)
        self.hotkeys = HotkeyManager(config.hotkeys, {
            "capture_event": self.open_capture_menu,
            "new_scene": self.new_scene,
        })
        self._window_callback = None
        self._capture_menu_callback = None
        self.last_handoff = ""
        self.discord_router = None
        self.discord_bot = None
        self.relay_subscriber = None

    @property
    def is_listening(self) -> bool:
        return self.worker.running

    def set_show_window_callback(self, callback: object) -> None:
        self._window_callback = callback

    def set_capture_menu_callback(self, callback: object) -> None:
        self._capture_menu_callback = callback

    def update_hotkeys(self, capture_event: str, new_scene: str) -> None:
        capture_event, new_scene = capture_event.strip(), new_scene.strip()
        if not capture_event or not new_scene:
            raise ValueError("Both shortcuts need a key combination.")
        was_running = self.worker.running
        if was_running:
            self.hotkeys.stop()
        self.config.hotkeys.capture_event = capture_event
        self.config.hotkeys.new_scene = new_scene
        save_config(self.config)
        if was_running:
            self.hotkeys.start()

    def update_whisper_model(self, model: str) -> None:
        if model not in WHISPER_MODELS:
            raise ValueError("Choose one of the available Whisper models")
        self.config.whisper.model = model
        save_config(self.config)

    def create_session(self, name: str) -> Path:
        return self.session.create_session(name)

    def rename_session(self, name: str) -> Path:
        if self.discord_router is not None:
            self.discord_router.release_archives()
        return self.session.rename_session(name)

    def set_vault_directory(self, directory: str) -> None:
        path = Path(directory).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("Choose an existing Obsidian vault folder")
        self.config.vault.directory = str(path)
        save_config(self.config)

    def start_listening(self) -> None:
        self._ensure_session()
        try:
            self.worker.start()
            self.hotkeys.start()
            if self.relay_subscriber is None:
                from app.relay.subscriber import RelaySubscriber
                self.relay_subscriber = RelaySubscriber(self.config.relay.endpoint, self.config.relay.room, self.config.relay.token_file, self.worker.submit_audio)
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
        self.hotkeys.stop()
        LOGGER.info("Listening stopped")

    def _on_entry(self, entry: TranscriptEntry) -> None:
        try:
            self.session.add_entry(entry)
        except Exception:
            LOGGER.exception("Could not save transcript entry")

    def mark_important(self) -> str:
        marked = self.notes.mark_recent(self.config.context.important_note_seconds)
        self.last_handoff = "Recent transcript saved to notes" if marked else "No recent transcript to mark"
        self._notify()
        return marked

    def add_note(self, text: str) -> None:
        self._ensure_session()
        self.notes.add_manual(text)
        self.last_handoff = "Note saved"

    def new_scene(self) -> None:
        self._ensure_session()
        self.session.add_entry(TranscriptEntry.scene())
        self.last_handoff = "New scene marked"
        self._notify()

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

    def open_capture_menu(self) -> None:
        self.show_window()
        if callable(self._capture_menu_callback):
            self._capture_menu_callback()

    def show_window(self) -> None:
        if callable(self._window_callback):
            self._window_callback()

    def open_session_folder(self) -> None:
        if self.session.session_dir:
            if hasattr(os, "startfile"):
                os.startfile(self.session.session_dir)
            else:
                LOGGER.info("Session folder: %s", self.session.session_dir)

    def session_processing_prompt(self) -> str:
        """Build a self-contained prompt that can be pasted directly into ChatGPT."""
        self._ensure_session()
        assert self.session.session_dir is not None
        session_dir = self.session.session_dir
        transcript_path = session_dir / "transcript.txt"
        notes_path = session_dir / "notes.md"
        transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
        notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
        images = sorted((session_dir / "images").glob("*")) if (session_dir / "images").exists() else []
        image_list = "\n".join(f"- {image}" for image in images) or "- No event images were attached."
        vault_directory = self.config.vault.directory or "[No Obsidian vault folder has been selected yet.]"
        return textwrap.dedent(
            f"""\
            # D&D Session → Obsidian Vault Processing Request

            Process this D&D session conservatively and produce Obsidian-ready updates.

            ## Source files
            These are the local source paths for reference. The transcript and notes are included below so you can work from this pasted prompt.
            - Session folder: {session_dir}
            - Raw transcript: {transcript_path}
            - Session notes: {notes_path}
            - Event-image folder: {session_dir / 'images'}

            ## Obsidian vault destination
            Place the proposed Markdown files and edits in this vault:
            {vault_directory}
            If no vault folder is configured, ask me to select one before giving final file paths.

            Event images saved for this session:
            {image_list}

            ## Rules
            1. Treat the raw transcript as evidence, not reliable canon. It is speech-to-text and can contain errors.
            2. `DND_EVENT_START` / `DND_EVENT_END` blocks are explicit user captures. Use the dialogue immediately before and after each one to understand its context.
            3. Only create a new NPC, location, faction, item, quest, lore entry, or event when an explicit event marker says `CAPTURED_BY_USER: true` and `CANON_PERMISSION: CREATE_OR_UPDATE`. Otherwise, update existing vault material only or flag it for review.
            4. Resolve likely speech-to-text misspellings by matching sound-alikes and context to existing canonical vault names. Never silently create a near-duplicate. Record uncertain matches under `Needs review`.
            5. An `IMAGE: images/...` line refers to an image captured with that marker. If that image is attached to this chat, use it as supporting evidence; do not infer details that are not visible or supported by the transcript.
            6. Preserve uncertainty. Do not invent facts, names, relationships, or outcomes.

            ## Deliverable
            Return, in this order:
            1. A concise session recap.
            2. A marker-by-marker review: context, confidence, and whether it should create/update/review a vault note.
            3. Obsidian-ready Markdown for the session note and only the entity-note updates authorized by user markers.
            4. A `Needs review` list for uncertain names, details, or possible duplicate entities.

            ## RAW TRANSCRIPT
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
        self.session.close()
