from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.config import HotkeysConfig

LOGGER = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(self, config: HotkeysConfig, action: Callable[[dict[str, Any]], None]) -> None:
        self.config, self.action = config, action
        self._keyboard = None

    def start(self) -> None:
        try:
            import keyboard
            self._keyboard = keyboard
            for shortcut in self.config.shortcuts:
                if not isinstance(shortcut, dict) or not shortcut.get("enabled", True):
                    continue
                combo = str(shortcut.get("keys", "")).strip()
                if combo:
                    keyboard.add_hotkey(combo, self._run, args=(dict(shortcut),), suppress=False)
            LOGGER.info("Global hotkeys registered")
        except Exception as exc:
            LOGGER.exception("Global hotkeys unavailable")
            raise RuntimeError(f"Could not register global hotkeys: {exc}") from exc

    def _run(self, shortcut: dict[str, Any]) -> None:
        try:
            LOGGER.info("Hotkey triggered: %s", shortcut.get("action", "unknown"))
            self.action(shortcut)
        except Exception:
            LOGGER.exception("Hotkey action failed: %s", shortcut.get("action", "unknown"))

    def stop(self) -> None:
        if self._keyboard:
            self._keyboard.unhook_all_hotkeys()
            self._keyboard = None
