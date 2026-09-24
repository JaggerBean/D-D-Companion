"""Discord voice receiver. Discord supplies the speaker identity; Whisper never guesses it."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
import wave
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import yaml

from app.config import AudioConfig, DiscordConfig

if TYPE_CHECKING:
    from app.context.transcript_manager import SessionManager
    from app.transcription.worker import TranscriptionWorker

LOGGER = logging.getLogger(__name__)


class DiscordAudioRouter:
    """Batches independent member PCM streams, archives them, then submits labelled chunks."""
    def __init__(self, config: DiscordConfig, session: "SessionManager", worker: "TranscriptionWorker", audio: AudioConfig) -> None:
        self.config, self.session, self.worker = config, session, worker
        self._speech_threshold_db = audio.speech_threshold_db
        self._silence_seconds = max(0.3, audio.utterance_silence_seconds)
        self._max_samples = int(48000 * max(5.0, audio.max_utterance_seconds))
        self._preroll_samples = int(48000 * max(0.0, audio.utterance_preroll_seconds))
        self._buffers: dict[str, list[np.ndarray]] = defaultdict(list)
        self._lengths: dict[str, int] = defaultdict(int)
        self._prerolls: dict[str, list[np.ndarray]] = defaultdict(list)
        self._preroll_lengths: dict[str, int] = defaultdict(int)
        self._last_voice: dict[str, float] = {}
        self._active_sources: set[str] = set()
        self._files: dict[str, wave.Wave_write] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._flush_idle, name="discord-audio-flush", daemon=True)
        self._speaker_map = self._load_speaker_map()
        self._thread.start()

    def feed(self, user_id: int, display_name: str, pcm: bytes) -> None:
        if not pcm:
            return
        source = self._source(user_id, display_name)
        samples = np.frombuffer(pcm, dtype=np.int16).reshape(-1, 2).copy()
        now = time.monotonic()
        with self._lock:
            self._archive(source, pcm)
            if self._is_speech(samples):
                if source not in self._active_sources:
                    self._buffers[source] = self._prerolls.pop(source, [])
                    self._lengths[source] = self._preroll_lengths.pop(source, 0)
                    self._active_sources.add(source)
                self._append(source, samples)
                self._last_voice[source] = now
            elif source in self._active_sources:
                # Keep a little trailing silence; it helps Whisper finish a word
                # naturally without delaying the transcript until a fixed window.
                self._append(source, samples)
            else:
                self._append_preroll(source, samples)

            # A safety cap only affects unusually long uninterrupted monologues.
            # Everyday speech is submitted solely after a per-person pause.
            if source in self._active_sources and self._lengths[source] >= self._max_samples:
                LOGGER.info("Submitting a long Discord utterance from %s at the safety cap", source)
                self._submit(source, keep_tail=True)

    def _source(self, user_id: int, display_name: str) -> str:
        return self._speaker_map.get(str(user_id), self._speaker_map.get(display_name, display_name))

    def _append(self, source: str, samples: np.ndarray) -> None:
        self._buffers[source].append(samples)
        self._lengths[source] += len(samples)

    def _append_preroll(self, source: str, samples: np.ndarray) -> None:
        if not self._preroll_samples:
            return
        self._prerolls[source].append(samples)
        self._preroll_lengths[source] += len(samples)
        while self._prerolls[source] and self._preroll_lengths[source] > self._preroll_samples:
            removed = self._prerolls[source].pop(0)
            self._preroll_lengths[source] -= len(removed)

    def _submit(self, source: str, keep_tail: bool = False) -> None:
        chunks = self._buffers[source]
        if not chunks:
            return
        combined = np.concatenate(chunks)
        self._buffers[source], self._lengths[source] = [], 0
        self.worker.submit_audio(source, combined, 48000)
        LOGGER.info("Queued %.2fs utterance from %s", len(combined) / 48000, source)
        if keep_tail and self._preroll_samples:
            tail = combined[-self._preroll_samples:].copy()
            self._buffers[source] = [tail]
            self._lengths[source] = len(tail)

    def _is_speech(self, samples: np.ndarray) -> bool:
        mono = samples.astype(np.float32).mean(axis=1) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(mono)))) if len(mono) else 0.0
        db = 20 * np.log10(max(rms, 1e-9))
        return db >= self._speech_threshold_db

    def _flush_idle(self) -> None:
        while not self._stop.wait(0.4):
            with self._lock:
                self._flush_inactive(time.monotonic())

    def _flush_inactive(self, now: float) -> None:
        for source in list(self._active_sources):
            if now - self._last_voice.get(source, now) >= self._silence_seconds:
                self._submit(source)
                self._active_sources.discard(source)
                self._last_voice.pop(source, None)

    def _archive(self, source: str, pcm: bytes) -> None:
        if not self.session.session_dir:
            return
        file = self._files.get(source)
        if file is None:
            audio_dir = self.session.session_dir / "audio"
            audio_dir.mkdir(exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", source).strip("_") or "speaker"
            path = audio_dir / f"{safe}.wav"
            file = wave.open(str(path), "wb")
            file.setnchannels(2)
            file.setsampwidth(2)
            file.setframerate(48000)
            self._files[source] = file
        file.writeframesraw(pcm)

    def _load_speaker_map(self) -> dict[str, str]:
        path = Path(self.config.speaker_map_file)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            entries = raw.get("speakers", raw) if isinstance(raw, dict) else {}
            if not isinstance(entries, dict):
                return {}
            return {str(key): str(value) for key, value in entries.items()}
        except (OSError, yaml.YAMLError, TypeError, ValueError):
            return {}

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        with self._lock:
            for source in list(self._active_sources):
                self._submit(source)
            self.release_archives()

    def release_archives(self) -> None:
        """Close WAV handles so Windows can rename the active session folder.

        The next received frame opens a new handle in the renamed location;
        Discord receiving and utterance buffering continue uninterrupted.
        """
        with self._lock:
            for file in self._files.values():
                file.close()
            self._files.clear()


class DiscordVoiceBot:
    """Local bot process. `/join` connects it to caller's voice channel."""
    def __init__(self, config: DiscordConfig, router: DiscordAudioRouter) -> None:
        self.config, self.router = config, router
        self.status = "stopped"
        self.last_error = ""
        self._thread: threading.Thread | None = None
        self._bot = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        token = self._token()
        if not token:
            raise RuntimeError(f"Discord bot token missing. Put DISCORD_BOT_TOKEN=... in {self.config.token_file}")
        self.status = "starting"
        self._thread = threading.Thread(target=self._run, args=(token,), name="discord-bot", daemon=True)
        self._thread.start()

    def _run(self, token: str) -> None:
        try:
            import discord
            from discord.ext import commands, voice_recv

            router = self.router
            outer = self

            def can_control(interaction: discord.Interaction) -> bool:
                allowed = set(outer.config.controller_user_ids)
                if allowed:
                    return str(interaction.user.id) in allowed
                permissions = getattr(interaction.user, "guild_permissions", None)
                return bool(permissions and permissions.manage_guild)

            class PerMemberSink(voice_recv.AudioSink):
                def __init__(self) -> None:
                    # AudioSink owns the receive-chain state.  Without its
                    # initializer a bot can join successfully but never route
                    # decoded member frames into this sink.
                    super().__init__()
                    self._last_received_log = 0.0

                def wants_opus(self) -> bool:
                    return False

                def write(self, user: discord.User | None, data: object) -> None:
                    pcm = getattr(data, "pcm", b"")
                    if user is not None and pcm:
                        now = time.monotonic()
                        if now - self._last_received_log >= 15:
                            LOGGER.info("Receiving Discord audio from %s", getattr(user, "display_name", user.name))
                            self._last_received_log = now
                        router.feed(user.id, getattr(user, "display_name", user.name), pcm)

                def cleanup(self) -> None:
                    return None

            intents = discord.Intents.none()
            intents.guilds = True
            intents.voice_states = True
            bot = commands.Bot(command_prefix="!", intents=intents)
            self._bot = bot

            async def join(interaction: discord.Interaction) -> None:
                if not can_control(interaction):
                    await interaction.response.send_message("Only a configured controller or server manager can control recording.", ephemeral=True)
                    return
                voice_state = getattr(interaction.user, "voice", None)
                channel = voice_state and voice_state.channel
                if channel is None:
                    await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
                    return
                existing = interaction.guild.voice_client if interaction.guild else None
                if existing:
                    if existing.is_listening():
                        existing.stop_listening()
                    await existing.move_to(channel)
                else:
                    existing = await channel.connect(cls=voice_recv.VoiceRecvClient)
                existing.listen(PerMemberSink())
                outer.status = f"listening: {channel.name}"
                await interaction.response.send_message(f"Listening in {channel.name}. Audio stays local.", ephemeral=True)

            @bot.tree.command(name="join", description="Join your voice channel and start local transcription")
            async def join_command(interaction: discord.Interaction) -> None:
                await join(interaction)

            @bot.tree.command(name="leave", description="Stop listening and leave voice")
            async def leave_command(interaction: discord.Interaction) -> None:
                if not can_control(interaction):
                    await interaction.response.send_message("Only a configured controller or server manager can control recording.", ephemeral=True)
                    return
                client = interaction.guild and interaction.guild.voice_client
                if client:
                    client.stop_listening()
                    await client.disconnect(force=True)
                outer.status = "ready; not in voice"
                await interaction.response.send_message("Left voice channel.", ephemeral=True)

            @bot.tree.command(name="whoami", description="Show Discord identity for character mapping")
            async def whoami_command(interaction: discord.Interaction) -> None:
                await interaction.response.send_message(f"Discord ID: {interaction.user.id}\nDisplay name: {interaction.user.display_name}", ephemeral=True)

            @bot.event
            async def on_ready() -> None:
                outer.status = "ready; use /join in your server"
                guild_id = outer.config.application_guild_id.strip()
                if guild_id:
                    guild = discord.Object(id=int(guild_id))
                    bot.tree.copy_global_to(guild=guild)
                    await bot.tree.sync(guild=guild)
                else:
                    # Make commands available immediately in every server where
                    # the bot is installed. Global Discord propagation can
                    # otherwise take up to an hour on initial setup.
                    for guild in bot.guilds:
                        bot.tree.copy_global_to(guild=guild)
                        await bot.tree.sync(guild=guild)
                auto = outer.config.auto_join_voice_channel_id.strip()
                if auto:
                    channel = bot.get_channel(int(auto))
                    if channel:
                        client = await channel.connect(cls=voice_recv.VoiceRecvClient)
                        client.listen(PerMemberSink())
                        outer.status = f"listening: {channel.name}"

            bot.run(token, log_handler=None)
        except Exception as exc:
            self.last_error = str(exc)
            self.status = "failed"
            LOGGER.exception("Discord bot stopped")

    def stop(self) -> None:
        if self._bot and getattr(self._bot, "loop", None):
            future = asyncio.run_coroutine_threadsafe(self._bot.close(), self._bot.loop)
            try:
                future.result(timeout=8)
            except Exception:
                LOGGER.exception("Could not stop Discord bot cleanly")
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = self._bot = None
        self.status = "stopped"

    def _token(self) -> str:
        token_path = Path(self.config.token_file)
        if token_path.exists():
            for line in token_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("DISCORD_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"')
        return os.environ.get("DISCORD_BOT_TOKEN", "")
