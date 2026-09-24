"""Crash-safe transcript/session persistence and in-memory rolling context."""
from __future__ import annotations

import base64
import json
import sqlite3
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.models.transcript_entry import TranscriptEntry


class SessionManager:
    def __init__(self, sessions_root: Path) -> None:
        self.sessions_root = sessions_root
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.session_dir: Path | None = None
        self._entries: deque[TranscriptEntry] = deque(maxlen=5000)
        self._db = sqlite3.connect(self.sessions_root / "sessions.db", check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS sessions (name TEXT PRIMARY KEY, path TEXT NOT NULL, created_at TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS entries (session_name TEXT NOT NULL, timestamp TEXT NOT NULL, source TEXT NOT NULL, text TEXT NOT NULL, confidence REAL, scene_marker INTEGER NOT NULL DEFAULT 0)")
        self._db.commit()
        self.session_name = ""
        self._session_key = ""

    def create_session(self, name: str) -> Path:
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "session"
        stamp = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            self.session_name = safe_name
            self.session_dir = self._available_session_dir(stamp, safe_name)
            self.session_dir.mkdir(parents=True, exist_ok=False)
            self._session_key = self.session_dir.name
            metadata = {"name": safe_name, "created_at": datetime.now(timezone.utc).isoformat(), "version": 1}
            (self.session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            (self.session_dir / "transcript.jsonl").touch()
            (self.session_dir / "transcript.txt").touch()
            (self.session_dir / "notes.md").write_text("# Important Session Notes\n\n", encoding="utf-8")
            self._entries.clear()
            self._db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)", (self._session_key, str(self.session_dir), metadata["created_at"]))
            self._db.commit()
            return self.session_dir

    def resume_session(self, path: Path) -> None:
        if not (path / "metadata.json").exists():
            raise ValueError(f"Not a D&D Companion session: {path}")
        metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        entries: deque[TranscriptEntry] = deque(maxlen=5000)
        transcript = path / "transcript.jsonl"
        if transcript.exists():
            for line in transcript.read_text(encoding="utf-8").splitlines():
                try:
                    entries.append(TranscriptEntry.from_dict(json.loads(line)))
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
        with self._lock:
            self.session_dir, self.session_name, self._entries = path, metadata.get("name", path.name), entries
            row = self._db.execute("SELECT name FROM sessions WHERE path = ?", (str(path),)).fetchone()
            self._session_key = row[0] if row else path.name

    def rename_session(self, name: str) -> Path:
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip() or "session"
        with self._lock:
            if not self.session_dir:
                return self.create_session(safe_name)
            metadata_path = self.session_dir / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            date_prefix = datetime.fromisoformat(metadata["created_at"]).strftime("%Y-%m-%d")
            target = self._available_session_dir(date_prefix, safe_name, exclude=self.session_dir)
            old_key = self._session_key
            if target != self.session_dir:
                self.session_dir.rename(target)
                self.session_dir = target
            self.session_name, self._session_key = safe_name, self.session_dir.name
            metadata["name"] = safe_name
            (self.session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            self._db.execute("UPDATE sessions SET name = ?, path = ? WHERE name = ?", (self._session_key, str(self.session_dir), old_key))
            self._db.execute("UPDATE entries SET session_name = ? WHERE session_name = ?", (self._session_key, old_key))
            self._db.commit()
            return self.session_dir

    def _available_session_dir(self, date_prefix: str, name: str, exclude: Path | None = None) -> Path:
        candidate = self.sessions_root / f"{date_prefix}_{name}"
        suffix = 2
        while candidate.exists() and candidate != exclude:
            candidate = self.sessions_root / f"{date_prefix}_{name}-{suffix}"
            suffix += 1
        return candidate

    def add_entry(self, entry: TranscriptEntry) -> None:
        with self._lock:
            if not self.session_dir:
                raise RuntimeError("Create or resume a session first")
            self._entries.append(entry)
            with (self.session_dir / "transcript.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
                file.flush()
            with (self.session_dir / "transcript.txt").open("a", encoding="utf-8") as file:
                file.write(entry.display() + "\n")
                file.flush()
            self._db.execute("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)", (self._session_key, entry.timestamp, entry.source, entry.text, entry.confidence, int(entry.scene_marker)))
            self._db.commit()

    def insert_entry_after(self, index: int, entry: TranscriptEntry) -> None:
        """Insert a user-authored marker directly after a saved transcript entry."""
        with self._lock:
            if not self.session_dir or not 0 <= index < len(self._entries):
                raise ValueError("Transcript entry no longer exists")
            entries = list(self._entries)
            entries.insert(index + 1, entry)
            self._entries = deque(entries, maxlen=5000)
            self._rewrite_entries_locked(entries)

    def save_event_image(self, data_url: str, original_name: str = "") -> str:
        """Store an event image inside the active session and return its relative path."""
        if not data_url or not data_url.startswith("data:"):
            raise ValueError("Choose a supported image first")
        try:
            header, encoded = data_url.split(",", 1)
            mime = header[5:].split(";", 1)[0].lower()
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, UnicodeError):
            raise ValueError("That image could not be read") from None
        extensions = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
        if mime not in extensions:
            raise ValueError("Use a PNG, JPG, WebP, or GIF image")
        if not image_bytes or len(image_bytes) > 8 * 1024 * 1024:
            raise ValueError("Images must be smaller than 8 MB")
        with self._lock:
            if not self.session_dir:
                raise RuntimeError("Create or resume a session first")
            images_dir = self.session_dir / "images"
            images_dir.mkdir(exist_ok=True)
            suffix = extensions[mime]
            filename = f"event-{datetime.now().strftime('%H%M%S')}-{uuid4().hex[:8]}{suffix}"
            (images_dir / filename).write_bytes(image_bytes)
            return f"images/{filename}"

    def recent(self, seconds: int, after_last_scene: bool = True) -> list[TranscriptEntry]:
        cutoff = datetime.now(timezone.utc).astimezone() - timedelta(seconds=seconds)
        with self._lock:
            entries = list(self._entries)
        if after_last_scene:
            markers = [index for index, item in enumerate(entries) if item.scene_marker]
            if markers:
                entries = entries[markers[-1] + 1 :]
        return [entry for entry in entries if datetime.fromisoformat(entry.timestamp) >= cutoff and not entry.scene_marker]

    def latest(self, seconds: int) -> list[TranscriptEntry]:
        return self.recent(seconds, after_last_scene=False)

    def current_scene_tail(self, maximum_words: int) -> list[TranscriptEntry]:
        """Return the newest complete dialogue turns from the current scene.

        A word budget keeps prompts useful during a long session while avoiding
        the brittle time-only context window that could omit the setup of a
        conversation still happening in the same scene.
        """
        with self._lock:
            entries = list(self._entries)
        markers = [index for index, item in enumerate(entries) if item.scene_marker]
        if markers:
            entries = entries[markers[-1] + 1 :]
        entries = [entry for entry in entries if not entry.scene_marker]
        chosen: list[TranscriptEntry] = []
        used = 0
        for entry in reversed(entries):
            words = len(entry.display().split())
            if chosen and used + words > maximum_words:
                break
            chosen.append(entry)
            used += words
        return list(reversed(chosen))

    def all_entries(self) -> list[TranscriptEntry]:
        with self._lock:
            return list(self._entries)

    def update_entry(self, index: int, text: str) -> None:
        """Apply an explicit user correction and rebuild session transcript files."""
        cleaned = " ".join(text.split())
        if not cleaned:
            raise ValueError("Transcript text cannot be empty")
        with self._lock:
            if not self.session_dir or not 0 <= index < len(self._entries):
                raise ValueError("Transcript entry no longer exists")
            entries = list(self._entries)
            entries[index] = replace(entries[index], text=cleaned)
            self._entries = deque(entries, maxlen=5000)
            self._rewrite_entries_locked(entries)

    def _rewrite_entries_locked(self, entries: list[TranscriptEntry]) -> None:
        """Atomically rebuild text/JSONL exports and their SQLite index while locked."""
        if not self.session_dir:
            raise RuntimeError("Create or resume a session first")
        jsonl = self.session_dir / "transcript.jsonl"
        text_file = self.session_dir / "transcript.txt"
        jsonl_tmp, text_tmp = jsonl.with_suffix(".jsonl.tmp"), text_file.with_suffix(".txt.tmp")
        jsonl_tmp.write_text("".join(json.dumps(item.to_dict(), ensure_ascii=False) + "\n" for item in entries), encoding="utf-8")
        text_tmp.write_text("".join(item.display() + "\n" for item in entries), encoding="utf-8")
        jsonl_tmp.replace(jsonl)
        text_tmp.replace(text_file)
        self._db.execute("DELETE FROM entries WHERE session_name = ?", (self._session_key,))
        self._db.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?)", [(self._session_key, item.timestamp, item.source, item.text, item.confidence, int(item.scene_marker)) for item in entries])
        self._db.commit()

    def add_note(self, text: str) -> None:
        if not text.strip():
            return
        with self._lock:
            if not self.session_dir:
                raise RuntimeError("Create or resume a session first")
            with (self.session_dir / "notes.md").open("a", encoding="utf-8") as file:
                file.write(f"- {text.strip()}\n")

    def notes(self) -> str:
        with self._lock:
            if not self.session_dir:
                return ""
            path = self.session_dir / "notes.md"
            return path.read_text(encoding="utf-8") if path.exists() else ""

    def close(self) -> None:
        self._db.close()
