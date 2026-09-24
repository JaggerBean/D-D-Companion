"""React dashboard bridge. No browser server or external service is used."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.config import ROOT
from app.controller import AppController


class DashboardApi:
    def __init__(self, controller: AppController) -> None:
        self.controller = controller
        self._window = None

    def set_window(self, window: object) -> None:
        """Keep the native window private; only API methods should be exposed to JavaScript."""
        self._window = window

    def get_state(self) -> dict[str, Any]:
        all_entries = self.controller.session.all_entries()
        start_index = max(0, len(all_entries) - 400)
        return {
            "status": self.controller.status(),
            "whisper": {
                "model": self.controller.config.whisper.model,
                "available_models": ["large-v3-turbo", "distil-large-v3", "medium", "small"],
                "active_device": self.controller.engine.active_device,
                "is_active": self.controller.is_listening,
            },
            "vault_path": self.controller.config.vault.directory,
            "vault_setup_required": not bool(self.controller.config.vault.directory),
            "ai_instructions": self.controller.config.ai.instructions,
            "entries": [
                {"index": index, "source": entry.source, "text": entry.text, "time": entry.display_time, "timestamp": entry.timestamp}
                for index, entry in enumerate(all_entries[start_index:], start=start_index)
            ],
            "notes": self.controller.session.notes(),
            "active_scene": self.controller.active_scene(),
            "hotkeys": {
                "shortcuts": self.controller.config.hotkeys.shortcuts,
            },
            "participants": self.controller.participants(),
            "update": self.controller.updates.status(),
        }

    def start_bot(self) -> dict[str, str]:
        self.controller.start_listening()
        return {"message": "Starting relay listener…"}

    def stop_bot(self) -> dict[str, str]:
        self.controller.stop_listening()
        return {"message": "Relay listener stopped."}

    def new_scene(self, label: str = "", shortcut_id: str = "") -> dict[str, str]:
        self.controller.new_scene(label, shortcut_id)
        return {"message": "Scene started." if not label.strip() else f"Scene started: {' '.join(label.split())}."}

    def end_scene(self) -> dict[str, str]:
        self.controller.end_scene()
        return {"message": "Scene ended."}

    def add_event_marker(
        self,
        event_type: str,
        label: str = "",
        details: str = "",
        image_data: str = "",
        image_name: str = "",
        after_index: int | None = None,
    ) -> dict[str, str]:
        self.controller.add_event_marker(event_type, label, details, image_data, image_name, after_index)
        placement = "inserted after that transcript entry" if after_index is not None else "added to transcript"
        return {"message": f"{event_type.title()} marker {placement}."}

    def update_transcript_entry(self, index: int, text: str) -> dict[str, str]:
        self.controller.update_transcript_entry(int(index), text)
        return {"message": "Transcript entry updated."}

    def update_participant(self, member_id: str, nickname: str, enabled: bool, icon_data: str = "", clear_icon: bool = False) -> dict[str, str]:
        changed = self.controller.update_participant(member_id, nickname, enabled, icon_data, clear_icon)
        suffix = f" Updated {changed} transcript line{'s' if changed != 1 else ''}." if changed else ""
        return {"message": f"Participant settings saved.{suffix}"}

    def save_shortcuts(self, shortcuts: list[dict[str, object]]) -> dict[str, str]:
        self.controller.update_shortcuts(shortcuts)
        return {"message": "Shortcuts saved."}

    def save_whisper_model(self, model: str) -> dict[str, str]:
        self.controller.update_whisper_model(model)
        return {"message": "Whisper model saved. It will be used the next time you start the relay listener."}

    def rename_session(self, name: str) -> dict[str, str]:
        cleaned = " ".join(name.split())
        if not cleaned:
            raise ValueError("Give the session a name first.")
        self.controller.rename_session(cleaned)
        return {"message": f"Session renamed to: {cleaned}"}

    def add_note(self, text: str) -> dict[str, str]:
        self.controller.add_note(text)
        return {"message": "Important note saved."}

    def open_session_folder(self) -> dict[str, str]:
        self.controller.open_session_folder()
        return {"message": "Opened session folder."}

    def copy_ai_prompt(self) -> dict[str, str]:
        self.controller.copy_session_processing_prompt()
        return {"message": "AI session prompt copied. Paste it into ChatGPT; attach any event images you want it to inspect."}

    def check_for_updates(self) -> dict[str, object]:
        return self.controller.check_for_updates()

    def install_update(self) -> dict[str, object]:
        status = self.controller.install_update()
        return {"message": str(status.get("message", "Update installer started."))}

    def choose_vault_folder(self) -> dict[str, str]:
        if not self._window:
            raise RuntimeError("The folder chooser is not ready yet")
        import webview

        selected = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not selected:
            return {"message": "Vault folder was not changed."}
        self.controller.set_vault_directory(str(selected[0]))
        return {"message": "Obsidian vault folder saved."}

    def create_vault_folder(self, name: str) -> dict[str, str]:
        if not self._window:
            raise RuntimeError("The folder chooser is not ready yet")
        import webview

        selected = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not selected:
            return {"message": "Vault creation was cancelled."}
        vault = self.controller.create_vault_directory(str(selected[0]), name)
        return {"message": f"New Obsidian vault created: {vault.name}."}

    def save_ai_instructions(self, instructions: str) -> dict[str, str]:
        self.controller.update_ai_instructions(instructions)
        return {"message": "AI instructions saved in D&D Companion."}

    def get_debug_log(self) -> str:
        path = ROOT / "logs" / "app.log"
        if not path.exists():
            return "No log has been created yet."
        with path.open("rb") as file:
            file.seek(max(0, path.stat().st_size - 150_000))
            lines = file.read().decode("utf-8", errors="replace").splitlines()
        return "\n".join(line for line in lines if line.strip())[-60_000:]


def run_dashboard(controller: AppController) -> None:
    import webview

    # The taskbar otherwise groups this source-installed app with pythonw.exe
    # and shows Python's icon instead of the D&D Companion window icon.
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ObsidianKingdom.DNDCompanion"
            )
        except Exception:
            pass

    frontend = ROOT / "app" / "ui" / "web" / "index.html"
    if not frontend.exists():
        raise RuntimeError("Dashboard files are missing. Run setup.bat again.")
    dashboard_api = DashboardApi(controller)
    window = webview.create_window("D&D Companion", frontend.as_uri(), js_api=dashboard_api, width=1280, height=760, min_size=(760, 540))
    dashboard_api.set_window(window)
    controller.set_show_window_callback(lambda: window.show())
    controller.set_capture_menu_callback(
        lambda event_type="": window.evaluate_js(
            f"window.dispatchEvent(new CustomEvent('dnd-open-capture', {{detail: {json.dumps(event_type)}}}))"
        )
    )
    controller.set_scene_menu_callback(
        lambda shortcut_id="": window.evaluate_js(
            f"window.dispatchEvent(new CustomEvent('dnd-open-scene', {{detail: {json.dumps({'shortcutId': shortcut_id})}}}))"
        )
    )
    controller.hotkeys.start()
    controller.check_for_updates_async()
    window.events.closed += lambda *_args: controller.shutdown()
    icon = ROOT / "app" / "assets" / "dnd-companion.ico"
    webview.start(gui="edgechromium", debug=False, icon=str(icon) if icon.exists() else None)
