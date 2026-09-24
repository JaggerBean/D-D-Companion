from __future__ import annotations

from app.context.transcript_manager import SessionManager


class NotesManager:
    def __init__(self, session: SessionManager) -> None:
        self.session = session

    def mark_recent(self, seconds: int) -> str:
        entries = self.session.latest(seconds)
        if not entries:
            return ""
        text = "\n".join(entry.display() for entry in entries)
        self.session.add_note(text)
        return text

    def add_manual(self, text: str) -> None:
        self.session.add_note(text)
