from __future__ import annotations

import tempfile
from unittest.mock import patch

import pytest

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


def test_new_campaign_requires_an_existing_vault_folder() -> None:
    controller = AppController(AppConfig())
    with patch("app.controller.save_config"):
        with pytest.raises(ValueError, match="Obsidian vault folder"):
            controller.create_campaign("D&D Campaign")
        with tempfile.TemporaryDirectory() as vault:
            campaign = controller.create_campaign("D&D Campaign", vault)

    assert campaign.vault_directory == vault
