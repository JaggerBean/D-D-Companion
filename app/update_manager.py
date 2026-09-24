"""Public GitHub Release updates for the installed Windows companion."""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from app.version import APP_VERSION, REPOSITORY

LOGGER = logging.getLogger(__name__)


class UpdateManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: dict[str, object] = {
            "state": "idle",
            "current_version": APP_VERSION,
            "latest_version": APP_VERSION,
            "download_url": "",
            "asset_name": "",
            "digest": "",
            "message": "",
        }

    def status(self) -> dict[str, object]:
        with self._lock:
            return dict(self._status)

    def check_async(self) -> None:
        if self.status().get("state") == "checking":
            return
        threading.Thread(target=self.check, name="update-check", daemon=True).start()

    def check(self) -> dict[str, object]:
        self._set(state="checking", message="Checking for updates…")
        try:
            request = Request(
                f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "DND-Companion-Updater"},
            )
            with urlopen(request, timeout=12) as response:
                release = json.loads(response.read().decode("utf-8"))
            tag = str(release.get("tag_name", "")).lstrip("vV").strip()
            assets = release.get("assets") if isinstance(release.get("assets"), list) else []
            installer = next(
                (
                    asset for asset in assets
                    if isinstance(asset, dict)
                    and str(asset.get("name", "")).lower().endswith("-setup.exe")
                ),
                None,
            )
            if not tag or not installer or not isinstance(installer.get("browser_download_url"), str):
                raise RuntimeError("The latest release does not include a D&D Companion installer.")
            if _version_key(tag) > _version_key(APP_VERSION):
                self._set(
                    state="available",
                    latest_version=tag,
                    download_url=str(installer["browser_download_url"]),
                    asset_name=str(installer.get("name", "DND-Companion-Setup.exe")),
                    digest=str(installer.get("digest", "")),
                    message=f"Version {tag} is ready to install.",
                )
            else:
                self._set(state="up_to_date", latest_version=tag, message="You have the latest version.")
        except Exception as exc:
            LOGGER.warning("Update check failed: %s", exc)
            self._set(state="error", message="Could not check for updates. Try again later.")
        return self.status()

    def install(self) -> dict[str, object]:
        status = self.status()
        if status.get("state") != "available":
            status = self.check()
        if status.get("state") != "available":
            raise RuntimeError(str(status.get("message") or "No update is available."))
        self._set(state="downloading", message="Downloading the update…")
        try:
            folder = Path(tempfile.gettempdir()) / "DND-Companion-Updates"
            folder.mkdir(parents=True, exist_ok=True)
            installer = folder / str(status["asset_name"])
            request = Request(str(status["download_url"]), headers={"User-Agent": "DND-Companion-Updater"})
            with urlopen(request, timeout=60) as response, installer.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            digest = str(status.get("digest", ""))
            if digest.startswith("sha256:"):
                actual = hashlib.sha256(installer.read_bytes()).hexdigest()
                if actual.lower() != digest.split(":", 1)[1].lower():
                    installer.unlink(missing_ok=True)
                    raise RuntimeError("The update download did not pass its integrity check.")
            subprocess.Popen(
                [str(installer), "/SP-", "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"],
                close_fds=True,
            )
            self._set(state="installing", message="Installer started. D&D Companion will close to finish updating.")
        except Exception as exc:
            LOGGER.exception("Update download failed")
            self._set(state="error", message="Could not download the update. Try again later.")
            raise RuntimeError("Could not download the update.") from exc
        return self.status()

    def _set(self, **changes: object) -> None:
        with self._lock:
            self._status.update(changes)


def _version_key(value: str) -> tuple[int, ...]:
    pieces = []
    for part in value.split("."):
        digits = "".join(character for character in part if character.isdigit())
        pieces.append(int(digits or 0))
    return tuple((pieces + [0, 0, 0])[:3])
