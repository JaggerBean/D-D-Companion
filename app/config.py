"""Application configuration and path helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

import yaml


ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


@dataclass
class AudioConfig:
    capture_system_audio: bool = True
    capture_microphone: bool = True
    output_device: str = "auto"
    microphone_device: str = "auto"
    sample_rate: int = 48000
    channels: int = 1
    chunk_seconds: float = 4.0
    chunk_overlap_seconds: float = 1.0
    speech_threshold_db: float = -42.0
    utterance_silence_seconds: float = 0.8
    max_utterance_seconds: float = 18.0
    utterance_preroll_seconds: float = 0.25


@dataclass
class WhisperConfig:
    model: str = "large-v3-turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str = "en"
    vad: bool = True


@dataclass
class ContextConfig:
    recent_seconds: int = 900
    important_note_seconds: int = 30
    scene_dialogue_words: int = 1800
    max_prompt_words: int = 3600


@dataclass
class HotkeysConfig:
    roleplay: str = "f8"
    tactics: str = "f7"
    knowledge: str = "f6"
    questions: str = "f5"
    mark_important: str = "f9"
    control_panel: str = "f10"
    quick_roleplay: str = "ctrl+f8"
    capture_event: str = "ctrl+alt+m"
    new_scene: str = "ctrl+alt+s"
    # Kept alongside the two legacy fields so existing installations can be
    # upgraded without losing their chosen Event and Scene combinations.
    shortcuts: list[dict[str, Any]] = field(default_factory=lambda: default_shortcuts())


def default_shortcuts(capture_event: str = "ctrl+alt+m", new_scene: str = "ctrl+alt+s") -> list[dict[str, Any]]:
    """The initial shortcuts shown on upgraded and first-run installations."""
    return [
        {"id": "event-default", "action": "event", "event_type": "NPC", "keys": capture_event, "enabled": True},
        {"id": "scene-default", "action": "scene", "event_type": "", "keys": new_scene, "enabled": True},
    ]


@dataclass
class ChatGPTConfig:
    focus_window: bool = True
    window_title_contains: str = "ChatGPT"


@dataclass
class CharacterConfig:
    directory: str = "./character"
    include_summary_in_prompt: bool = False


@dataclass
class DiscordConfig:
    enabled: bool = True
    token_file: str = "./config/discord.env"
    application_guild_id: str = ""
    auto_join_voice_channel_id: str = ""
    speaker_map_file: str = "./config/speakers.yaml"
    controller_user_ids: list[str] = field(default_factory=list)


@dataclass
class RelayConfig:
    enabled: bool = True
    endpoint: str = "wss://dnd.stepcraft.org"
    room: str = "obsidian-kingdom"
    token_file: str = "./config/relay.env"


@dataclass
class VaultConfig:
    directory: str = ""


@dataclass
class CampaignConfig:
    id: str = field(default_factory=lambda: uuid4().hex)
    name: str = "D&D Campaign"
    vault_directory: str = ""
    participants: dict[str, dict[str, Any]] = field(default_factory=dict)


def default_campaigns() -> list[CampaignConfig]:
    return [CampaignConfig()]


def default_ai_instructions() -> str:
    """Default guidance included with every copied session-processing prompt."""
    return """## Processing rules
1. Treat dialogue text as evidence, not reliable canon. It is speech-to-text and can contain errors.
2. Treat `event_marker: true` as an explicit user capture. Use the dialogue immediately before and after it to understand the captured situation.
3. Only create a new NPC, location, faction, item, quest, lore entry, or event when an entry has `event_marker: true`, `captured_by_user: true`, and `canon_permission: \"CREATE_OR_UPDATE\"`. Otherwise, update existing vault material only or flag it for review.
4. Resolve likely speech-to-text misspellings by matching sound-alikes and context to existing canonical vault names. Never silently create a near-duplicate. Record uncertain matches under `Needs review`.
5. An `image_path` in a marked entry points to an image captured with that event. If that image is attached to this chat, use it as supporting evidence; do not infer details that are not visible or supported by the transcript.
6. Preserve uncertainty. Do not invent facts, names, relationships, or outcomes.

## Deliverable
Return, in this order:
1. A concise session recap.
2. A marker-by-marker review: context, confidence, and whether it should create/update/review a vault note.
3. Obsidian-ready Markdown for the session note and only the entity-note updates authorized by user markers.
4. A `Needs review` list for uncertain names, details, or possible duplicate entities."""


@dataclass
class AIConfig:
    instructions: str = field(default_factory=default_ai_instructions)


@dataclass
class AppConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    hotkeys: HotkeysConfig = field(default_factory=HotkeysConfig)
    chatgpt: ChatGPTConfig = field(default_factory=ChatGPTConfig)
    character: CharacterConfig = field(default_factory=CharacterConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    relay: RelayConfig = field(default_factory=RelayConfig)
    vault: VaultConfig = field(default_factory=VaultConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    participants: dict[str, dict[str, Any]] = field(default_factory=dict)
    campaigns: list[CampaignConfig] = field(default_factory=default_campaigns)
    active_campaign_id: str = ""
    setup_completed: bool = False


def config_path(root: Path = ROOT) -> Path:
    return root / "config.yaml"


def _section(cls: type, data: Any) -> Any:
    return cls(**(data if isinstance(data, dict) else {}))


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    if not path.exists():
        cfg = AppConfig()
        save_config(cfg, path)
        return cfg
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        hotkeys_data = raw.get("hotkeys") if isinstance(raw.get("hotkeys"), dict) else {}
        hotkeys = _section(HotkeysConfig, hotkeys_data)
        # An absent setting means this is an older config. An explicitly empty
        # list means the user intentionally removed every shortcut.
        if "shortcuts" not in hotkeys_data:
            hotkeys.shortcuts = default_shortcuts(hotkeys.capture_event, hotkeys.new_scene)
        campaigns_raw = raw.get("campaigns")
        migrated_campaigns = not (isinstance(campaigns_raw, list) and campaigns_raw)
        if isinstance(campaigns_raw, list) and campaigns_raw:
            campaigns = [
                _section(CampaignConfig, item)
                for item in campaigns_raw
                if isinstance(item, dict)
            ]
            campaigns = [campaign for campaign in campaigns if campaign.id.strip()]
        else:
            # Preserve all data from installations that predate campaigns.
            campaigns = [CampaignConfig(
                id="default",
                name="D&D Campaign",
                vault_directory=_section(VaultConfig, raw.get("vault")).directory,
                participants=raw.get("participants") if isinstance(raw.get("participants"), dict) else {},
            )]
        if not campaigns:
            campaigns = default_campaigns()
        active_campaign_id = str(raw.get("active_campaign_id", "")).strip()
        if active_campaign_id not in {campaign.id for campaign in campaigns}:
            active_campaign_id = campaigns[0].id
        config = AppConfig(
            audio=_section(AudioConfig, raw.get("audio")),
            whisper=_section(WhisperConfig, raw.get("whisper")),
            context=_section(ContextConfig, raw.get("context")),
            hotkeys=hotkeys,
            chatgpt=_section(ChatGPTConfig, raw.get("chatgpt")),
            character=_section(CharacterConfig, raw.get("character")),
            discord=_section(DiscordConfig, raw.get("discord")),
            relay=_section(RelayConfig, raw.get("relay")),
            vault=_section(VaultConfig, raw.get("vault")),
            ai=_section(AIConfig, raw.get("ai")),
            participants=raw.get("participants") if isinstance(raw.get("participants"), dict) else {},
            campaigns=campaigns,
            active_campaign_id=active_campaign_id,
            setup_completed=bool(raw.get("setup_completed", False)),
        )
        if migrated_campaigns:
            save_config(config, path)
        return config
    except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
        raise ValueError(f"Cannot read configuration {path}: {exc}") from exc


def save_config(config: AppConfig, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(asdict(config), sort_keys=False), encoding="utf-8")


def resolve_character_dir(config: AppConfig, root: Path = ROOT) -> Path:
    path = Path(config.character.directory)
    return path if path.is_absolute() else root / path
