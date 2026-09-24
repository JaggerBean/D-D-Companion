from __future__ import annotations

import ctypes
import logging
import os
import threading
from ctypes import wintypes
from collections.abc import Callable
from typing import Any

from app.config import HotkeysConfig

LOGGER = logging.getLogger(__name__)

WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
_SPECIAL_KEYS = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21,
    "pagedown": 0x22, "end": 0x23, "home": 0x24, "left": 0x25,
    "up": 0x26, "right": 0x27, "down": 0x28, "insert": 0x2D, "delete": 0x2E,
}


class HotkeyManager:
    """Register shortcuts with Windows itself, regardless of app focus."""

    def __init__(self, config: HotkeysConfig, action: Callable[[dict[str, Any]], None]) -> None:
        self.config, self.action = config, action
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._registered: dict[int, dict[str, Any]] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._ready.clear()
        self._registered = {}
        self._thread = threading.Thread(target=self._run, name="global-hotkeys", daemon=True)
        self._thread.start()
        if not self._ready.wait(4):
            self.stop()
            raise RuntimeError("Windows did not finish registering global shortcuts.")
        if self._registered:
            LOGGER.info("Global hotkeys registered with Windows: %s", len(self._registered))
        else:
            LOGGER.warning("No global shortcuts were registered")

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        if os.name != "nt":
            self._ready.set()
            LOGGER.warning("Global shortcuts are available only on Windows")
            return
        user32 = ctypes.windll.user32
        self._thread_id = int(ctypes.windll.kernel32.GetCurrentThreadId())
        shortcuts = [dict(item) for item in self.config.shortcuts if isinstance(item, dict) and item.get("enabled", True)]
        for identifier, shortcut in enumerate(shortcuts, start=1):
            combo = str(shortcut.get("keys", "")).strip()
            parsed = self._parse_combo(combo)
            if parsed is None:
                LOGGER.warning("Skipping unsupported global shortcut: %s", combo)
                continue
            modifiers, key = parsed
            if user32.RegisterHotKey(None, identifier, modifiers | MOD_NOREPEAT, key):
                self._registered[identifier] = shortcut
            else:
                LOGGER.warning("Windows could not register shortcut %s (error %s)", combo, ctypes.get_last_error())
        self._ready.set()
        message = wintypes.MSG()
        while not self._stop.is_set():
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result <= 0:
                break
            if message.message == WM_HOTKEY and (shortcut := self._registered.get(int(message.wParam))):
                self._run_action(shortcut)
        for identifier in tuple(self._registered):
            user32.UnregisterHotKey(None, identifier)
        self._registered.clear()

    @staticmethod
    def _parse_combo(combo: str) -> tuple[int, int] | None:
        parts = [part.strip().lower() for part in combo.split("+") if part.strip()]
        modifiers, key_name = 0, ""
        for part in parts:
            if part in {"ctrl", "control"}:
                modifiers |= MOD_CONTROL
            elif part == "alt":
                modifiers |= MOD_ALT
            elif part == "shift":
                modifiers |= MOD_SHIFT
            elif part in {"win", "windows", "super"}:
                modifiers |= MOD_WIN
            elif not key_name:
                key_name = part
            else:
                return None
        if len(key_name) == 1 and key_name.isalnum():
            return modifiers, ord(key_name.upper())
        if key_name.startswith("f") and key_name[1:].isdigit() and 1 <= int(key_name[1:]) <= 24:
            return modifiers, 0x70 + int(key_name[1:]) - 1
        key = _SPECIAL_KEYS.get(key_name)
        return (modifiers, key) if key is not None else None

    def _run_action(self, shortcut: dict[str, Any]) -> None:
        try:
            LOGGER.info("Global hotkey triggered: %s", shortcut.get("action", "unknown"))
            self.action(shortcut)
        except Exception:
            LOGGER.exception("Global hotkey action failed: %s", shortcut.get("action", "unknown"))

    def stop(self) -> None:
        self._stop.set()
        if self._thread_id and os.name == "nt":
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self._thread_id = None
