"""Receive labelled speaker segments from the relay for local transcription."""
from __future__ import annotations

import base64
import json
import logging
import threading
from pathlib import Path
from typing import Callable

import numpy as np

LOG = logging.getLogger(__name__)


class RelaySubscriber:
    def __init__(
        self,
        endpoint: str,
        room: str,
        token_file: str,
        on_audio: Callable[[str, str, np.ndarray, int], None],
        on_members: Callable[[list[dict[str, str]]], None],
    ) -> None:
        self.endpoint, self.room, self.on_audio, self.on_members = endpoint, room, on_audio, on_members
        self.token = self._token(Path(token_file))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error = ""
        self.status = "stopped"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not self.token:
            raise RuntimeError("Relay access key is missing. Run setup again or add RELAY_SUBSCRIBER_TOKEN to config/relay.env.")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="relay-subscriber", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self.status = "stopped"

    def _run(self) -> None:
        self.status = "connecting"
        while not self._stop.is_set():
            try:
                from websockets.sync.client import connect
                with connect(self.endpoint, open_timeout=12, close_timeout=3, max_size=2_500_000) as socket:
                    socket.send(json.dumps({"role": "subscriber", "token": self.token, "room": self.room}))
                    ready = json.loads(socket.recv())
                    if ready.get("type") != "ready":
                        raise RuntimeError("Relay rejected this listener")
                    self.status = "listening"
                    self.last_error = ""
                    LOG.info("Listening to remote D&D relay")
                    while not self._stop.is_set():
                        try:
                            raw = socket.recv(timeout=1)
                        except TimeoutError:
                            continue
                        if raw is None:
                            break
                        self._handle(raw)
            except Exception as exc:
                self.last_error = str(exc)
                self.status = "reconnecting"
                if not self._stop.is_set():
                    LOG.warning("Relay unavailable; retrying: %s", exc)
                    self._stop.wait(5)

    def _handle(self, raw: object) -> None:
        if not isinstance(raw, str):
            return
        packet = json.loads(raw)
        packet_type = packet.get("type")
        if packet_type == "members":
            raw_members = packet.get("members")
            if not isinstance(raw_members, list):
                return
            members = [
                {"id": item["id"], "name": item["name"], "avatar": item.get("avatar", "")}
                for item in raw_members
                if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("name"), str) and isinstance(item.get("avatar", ""), str)
            ]
            self.on_members(members)
            return
        if packet_type != "audio":
            return
        speaker, speaker_id, rate, encoded = packet.get("speaker"), packet.get("speaker_id", ""), packet.get("sample_rate"), packet.get("pcm16")
        if not isinstance(speaker, str) or not isinstance(rate, int) or not isinstance(encoded, str):
            return
        samples = np.frombuffer(base64.b64decode(encoded, validate=True), dtype=np.int16).copy()
        if len(samples):
            self.on_audio(speaker_id if isinstance(speaker_id, str) else speaker, speaker, samples, rate)

    @staticmethod
    def _token(path: Path) -> str:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("RELAY_SUBSCRIBER_TOKEN="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            pass
        return ""
