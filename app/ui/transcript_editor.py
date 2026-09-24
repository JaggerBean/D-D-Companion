from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app.context.transcript_manager import SessionManager


class TranscriptEditor(tk.Toplevel):
    """Small editor for correction of recognized lines; preserves source/time."""
    def __init__(self, parent: tk.Tk, session: SessionManager) -> None:
        super().__init__(parent)
        self.session = session
        self.entries = session.all_entries()
        self.selected = 0
        self.title("Correct transcript")
        self.geometry("760x460")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)
        self.listing = tk.Listbox(self, exportselection=False)
        self.listing.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        for entry in self.entries:
            self.listing.insert("end", entry.display())
        self.listing.bind("<<ListboxSelect>>", self._select)
        self.editor = tk.Text(self, wrap="word")
        self.editor.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        ttk.Button(self, text="Save Correction", command=self._save).grid(row=1, column=1, sticky="e", padx=10, pady=(0, 10))
        if self.entries:
            self.listing.selection_set(0)
            self._load(0)

    def _select(self, _: object) -> None:
        selection = self.listing.curselection()
        if selection:
            self._load(selection[0])

    def _load(self, index: int) -> None:
        self.selected = index
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.entries[index].text)

    def _save(self) -> None:
        try:
            value = self.editor.get("1.0", "end").strip()
            self.session.update_entry(self.selected, value)
            self.entries = self.session.all_entries()
            self.listing.delete(self.selected)
            self.listing.insert(self.selected, self.entries[self.selected].display())
            self.listing.selection_set(self.selected)
        except ValueError as exc:
            messagebox.showerror("Cannot save correction", str(exc), parent=self)
