from __future__ import annotations

import logging
from collections.abc import Callable

from app.config import HotkeysConfig

LOGGER = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(self, config: HotkeysConfig, actions: dict[str, Callable[[], None]]) -> None:
        self.config, self.actions = config, actions
        self._keyboard = None

    def start(self) -> None:
        try:
            import keyboard
            self._keyboard = keyboard
            for name, combo in vars(self.config).items():
                if name in self.actions:
                    keyboard.add_hotkey(combo, self._run, args=(name,), suppress=False)
            LOGGER.info("Global hotkeys registered")
        except Exception as exc:
            LOGGER.exception("Global hotkeys unavailable")
            raise RuntimeError(f"Could not register global hotkeys: {exc}") from exc

    def _run(self, name: str) -> None:
        try:
            LOGGER.info("Hotkey triggered: %s", name)
            self.actions[name]()
        except Exception:
            LOGGER.exception("Hotkey action failed: %s", name)

    def stop(self) -> None:
        if self._keyboard:
            self._keyboard.unhook_all_hotkeys()
            self._keyboard = None
