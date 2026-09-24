"""Application configuration and path helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import sys
from typing import Any

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
    participants: dict[str, dict[str, Any]] = field(default_factory=dict)
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
        return AppConfig(
            audio=_section(AudioConfig, raw.get("audio")),
            whisper=_section(WhisperConfig, raw.get("whisper")),
            context=_section(ContextConfig, raw.get("context")),
            hotkeys=_section(HotkeysConfig, raw.get("hotkeys")),
            chatgpt=_section(ChatGPTConfig, raw.get("chatgpt")),
            character=_section(CharacterConfig, raw.get("character")),
            discord=_section(DiscordConfig, raw.get("discord")),
            relay=_section(RelayConfig, raw.get("relay")),
            vault=_section(VaultConfig, raw.get("vault")),
            participants=raw.get("participants") if isinstance(raw.get("participants"), dict) else {},
            setup_completed=bool(raw.get("setup_completed", False)),
        )
    except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
        raise ValueError(f"Cannot read configuration {path}: {exc}") from exc


def save_config(config: AppConfig, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(asdict(config), sort_keys=False), encoding="utf-8")


def resolve_character_dir(config: AppConfig, root: Path = ROOT) -> Path:
    path = Path(config.character.directory)
    return path if path.is_absolute() else root / path
