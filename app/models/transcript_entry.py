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
    marker_type: str = ""
    event_type: str = ""
    label: str = ""
    details: str = ""
    image_path: str = ""
    captured_by_user: bool = False
    canon_permission: str = ""

    @classmethod
    def spoken(cls, source: str, text: str, confidence: float | None = None) -> "TranscriptEntry":
        return cls(datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), source, text.strip(), confidence)

    @classmethod
    def scene(cls, label: str = "") -> "TranscriptEntry":
        cleaned = " ".join(label.split())
        text = f"Scene: {cleaned}" if cleaned else "Scene"
        return cls(
            datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "SYSTEM",
            text,
            None,
            scene_marker=True,
            marker_type="scene",
            label=cleaned,
            captured_by_user=True,
        )

    @classmethod
    def event(cls, event_type: str, label: str = "", details: str = "", image_path: str = "") -> "TranscriptEntry":
        cleaned_type = " ".join(event_type.split()) or "Other"
        cleaned_label = " ".join(label.split())
        cleaned_details = " ".join(details.split())
        text = f"{cleaned_type}: {cleaned_label}" if cleaned_label else f"{cleaned_type} event"
        if cleaned_details:
            text += f"\n{cleaned_details}"
        if image_path.strip():
            text += "\nImage attached"
        return cls(
            datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "SYSTEM",
            text,
            None,
            event_marker=True,
            marker_type="event",
            event_type=cleaned_type,
            label=cleaned_label,
            details=cleaned_details,
            image_path=image_path.strip(),
            captured_by_user=True,
            canon_permission="CREATE_OR_UPDATE",
        )

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
