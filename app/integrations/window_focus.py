"""Optional Windows-only focus. No browser automation, no keyboard submission."""
from __future__ import annotations

import ctypes
import logging

LOGGER = logging.getLogger(__name__)


def focus_window(title_part: str) -> bool:
    if not hasattr(ctypes, "windll"):
        return False
    user32 = ctypes.windll.user32
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if title_part.lower() in buffer.value.lower():
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(callback_type(visit), 0)
    if not found:
        LOGGER.info("No ChatGPT window found to focus")
        return False
    hwnd = found[0]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    return bool(user32.SetForegroundWindow(hwnd))
