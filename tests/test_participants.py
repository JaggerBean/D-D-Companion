from __future__ import annotations

from unittest.mock import patch

from app.config import AppConfig
from app.controller import AppController


def test_participants_keep_last_known_discord_name_after_disconnect() -> None:
    controller = AppController(AppConfig())
    with patch("app.controller.save_config"):
        controller._on_relay_members([
            {"id": "1054502160454389781", "name": "Kaldor", "avatar": ""},
        ])
        controller._on_relay_members([])

    assert controller.participants() == [
        {
            "id": "1054502160454389781",
            "name": "Kaldor",
            "nickname": "",
            "enabled": True,
            "avatar": "",
        }
    ]
