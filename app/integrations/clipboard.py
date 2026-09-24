from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


def copy_text(text: str) -> None:
    import pyperclip
    pyperclip.copy(text)
    LOGGER.info("Prompt copied to clipboard (%s characters)", len(text))
