from __future__ import annotations

import tkinter as tk
import os
from tkinter import messagebox, ttk

from app.config import AppConfig, ROOT, save_config
from app.integrations.clipboard import copy_text


class SetupWizard(tk.Toplevel):
    def __init__(self, parent: tk.Tk, config: AppConfig, on_done: object) -> None:
        super().__init__(parent)
        self.config, self.on_done = config, on_done
        self.title("D&D Companion — First-run setup")
        self.resizable(False, False)
        self.grab_set()
        frame = ttk.Frame(self, padding=16)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="Discord bot setup", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(frame, text="Create a Discord bot, then put its token in config\\discord.env.", wraplength=450).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Button(frame, text="Open Token File", command=self._open_token_file).grid(row=2, column=0, sticky="w", pady=(6, 12))
        ttk.Label(frame, text="Test-server ID (recommended; slash commands appear immediately)").grid(row=3, column=0, columnspan=2, sticky="w")
        self.guild_id = ttk.Entry(frame, width=54)
        self.guild_id.insert(0, config.discord.application_guild_id)
        self.guild_id.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(2, 10))
        ttk.Label(frame, text="Whisper model").grid(row=5, column=0, sticky="w")
        self.model = ttk.Combobox(frame, values=["large-v3-turbo", "distil-large-v3", "medium", "small"], width=24, state="readonly")
        self.model.set(config.whisper.model)
        self.model.grid(row=6, column=0, sticky="w", pady=(2, 12))
        ttk.Button(frame, text="Test Clipboard", command=self._test_clipboard).grid(row=6, column=1, sticky="e")
        ttk.Label(frame, text="Discord provides each speaker's identity. CUDA is used when faster-whisper can load it.", wraplength=450).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Button(frame, text="Save and Continue", command=self._finish).grid(row=8, column=1, sticky="e")

    def _test_clipboard(self) -> None:
        try:
            copy_text("D&D Companion clipboard test")
            messagebox.showinfo("Clipboard", "Test text copied. Paste it anywhere to confirm.", parent=self)
        except Exception as exc:
            messagebox.showerror("Clipboard", str(exc), parent=self)

    def _finish(self) -> None:
        self.config.discord.application_guild_id = self.guild_id.get().strip()
        self.config.whisper.model = self.model.get()
        self.config.setup_completed = True
        save_config(self.config)
        self.destroy()
        if callable(self.on_done):
            self.on_done()

    def _open_token_file(self) -> None:
        path = ROOT / "config" / "discord.env"
        if not path.exists():
            path.write_text("DISCORD_BOT_TOKEN=replace-with-your-discord-bot-token\n", encoding="utf-8")
        if hasattr(os, "startfile"):
            os.startfile(path)
        else:
            messagebox.showinfo("Token file", str(path), parent=self)
