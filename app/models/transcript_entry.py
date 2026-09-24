from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TranscriptEntry:
    timestamp: str
    source: str
    text: str
    confidence: float | None = None
    scene_marker: bool = False
    event_marker: bool = False

    @classmethod
    def spoken(cls, source: str, text: str, confidence: float | None = None) -> "TranscriptEntry":
        return cls(datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), source, text.strip(), confidence)

    @classmethod
    def scene(cls, label: str = "") -> "TranscriptEntry":
        lines = ["[DND_SCENE_START]", "CAPTURED_BY_USER: true"]
        cleaned = " ".join(label.split())
        if cleaned:
            lines.append(f"LABEL: {cleaned}")
        lines.append("[DND_SCENE_END]")
        return cls(datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "SYSTEM", "\n".join(lines), None, True)

    @classmethod
    def event(cls, event_type: str, label: str = "", details: str = "", image_path: str = "") -> "TranscriptEntry":
        safe_type = " ".join(event_type.upper().split()) or "OTHER"
        lines = [
            "[DND_EVENT_START]",
            "CAPTURED_BY_USER: true",
            "CANON_PERMISSION: CREATE_OR_UPDATE",
            f"TYPE: {safe_type}",
        ]
        if label.strip():
            lines.append(f"LABEL: {' '.join(label.split())}")
        if details.strip():
            lines.append(f"DETAILS: {' '.join(details.split())}")
        if image_path.strip():
            lines.append(f"IMAGE: {image_path.strip()}")
        lines.append("[DND_EVENT_END]")
        return cls(datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "SYSTEM", "\n".join(lines), None, False, True)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TranscriptEntry":
        return cls(**value)

    @property
    def display_time(self) -> str:
        return datetime.fromisoformat(self.timestamp).strftime("%H:%M:%S")

    def display(self) -> str:
        return self.text if self.scene_marker or self.event_marker else f"[{self.display_time}] {self.source}: {self.text}"
