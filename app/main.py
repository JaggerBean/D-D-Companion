from __future__ import annotations

import logging
from pathlib import Path

from app.config import ROOT, load_config
from app.controller import AppController
from app.ui.dashboard import run_dashboard


def configure_logging() -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(ROOT / "logs" / "app.log", encoding="utf-8"), logging.StreamHandler()],
    )


def main() -> None:
    configure_logging()
    config = load_config()
    (ROOT / "config" / "vocabulary.txt").touch(exist_ok=True)
    (ROOT / "character").mkdir(exist_ok=True)
    controller = AppController(config)
    run_dashboard(controller)


if __name__ == "__main__":
    main()
