from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, ttk

from app.controller import AppController
from app.ui.setup_wizard import SetupWizard
from app.ui.transcript_editor import TranscriptEditor


class MainWindow(tk.Tk):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        controller.set_show_window_callback(lambda: self.after(0, self.show_panel))
        self.title("D&D Companion")
        self.geometry("1020x720")
        self.minsize(760, 520)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._seen = 0
        self._build()
        if not controller.config.setup_completed:
            self.after(200, lambda: SetupWizard(self, controller.config, self._after_wizard))
        self.after(400, self._refresh)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=3)
        root.columnconfigure(1, weight=2)
        root.rowconfigure(1, weight=1)
        controls = ttk.Frame(root)
        controls.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        for text, command in [
            ("Start Discord Bot", self._start), ("Stop Bot", self.controller.stop_listening),
            ("New Session", self._new_session), ("Open Session Folder", self.controller.open_session_folder),
            ("Roleplay (F8)", lambda: self.controller.copy_prompt("roleplay")),
            ("Tactics (F7)", lambda: self.controller.copy_prompt("tactics")),
            ("Knowledge (F6)", lambda: self.controller.copy_prompt("knowledge")),
            ("Mark Important (F9)", self.controller.mark_important),
            ("Correct Transcript", lambda: TranscriptEditor(self, self.controller.session)),
        ]:
            ttk.Button(controls, text=text, command=command).pack(side="left", padx=(0, 5))
        left = ttk.LabelFrame(root, text="LIVE TRANSCRIPT", padding=8)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.transcript = tk.Text(left, wrap="word", state="disabled", font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(left, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=scrollbar.set)
        self.transcript.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        right = ttk.Frame(root)
        right.grid(row=1, column=1, sticky="nsew")
        status_box = ttk.LabelFrame(right, text="STATUS", padding=8)
        status_box.pack(fill="x")
        self.status_vars = {key: tk.StringVar(value="—") for key in ("model", "discord", "session", "recording", "handoff", "error")}
        labels = {"model": "Whisper", "discord": "Discord bot", "session": "Session", "recording": "Recording", "handoff": "Clipboard", "error": "Error"}
        for row, key in enumerate(self.status_vars):
            ttk.Label(status_box, text=f"{labels[key]}:").grid(row=row, column=0, sticky="nw", padx=(0, 8))
            ttk.Label(status_box, textvariable=self.status_vars[key], wraplength=260).grid(row=row, column=1, sticky="nw")
        notes_box = ttk.LabelFrame(right, text="IMPORTANT NOTES", padding=8)
        notes_box.pack(fill="both", expand=True, pady=(8, 0))
        self.notes_preview = tk.Text(notes_box, height=9, wrap="word", state="disabled")
        self.notes_preview.pack(fill="both", expand=True)
        self.notes = tk.Text(notes_box, height=3, wrap="word")
        self.notes.pack(fill="x", pady=(6, 0))
        buttons = ttk.Frame(notes_box)
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Save Note", command=self._save_note).pack(side="left")
        ttk.Button(buttons, text="New Scene (Ctrl+F9)", command=self.controller.new_scene).pack(side="right")

    def _after_wizard(self) -> None:
        self.title("D&D Companion")

    def _start(self) -> None:
        try:
            self.controller.start_listening()
        except Exception as exc:
            self.controller.last_handoff = f"Could not start: {exc}"

    def _new_session(self) -> None:
        name = simpledialog.askstring("New Session", "Session name:", parent=self)
        if name:
            if self.controller.is_listening:
                self.controller.stop_listening()
            self.controller.create_session(name)
            self._seen = 0
            self.transcript.configure(state="normal")
            self.transcript.delete("1.0", "end")
            self.transcript.configure(state="disabled")

    def _save_note(self) -> None:
        text = self.notes.get("1.0", "end").strip()
        if text:
            self.controller.add_note(text)
            self.notes.delete("1.0", "end")

    def _refresh(self) -> None:
        status = self.controller.status()
        for key, value in status.items():
            self.status_vars[key].set(value or "—")
        entries = self.controller.session.all_entries()
        if self._seen > len(entries):
            self._seen = 0
        if len(entries) > self._seen:
            self.transcript.configure(state="normal")
            for entry in entries[self._seen:]:
                self.transcript.insert("end", entry.display() + "\n")
            self.transcript.see("end")
            self.transcript.configure(state="disabled")
            self._seen = len(entries)
        self.notes_preview.configure(state="normal")
        self.notes_preview.delete("1.0", "end")
        self.notes_preview.insert("1.0", self.controller.session.notes())
        self.notes_preview.configure(state="disabled")
        self.after(400, self._refresh)

    def show_panel(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _close(self) -> None:
        self.controller.shutdown()
        self.destroy()
