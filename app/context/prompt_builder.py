"""Build bounded, paste-ready prompts. Never sends data to any service."""
from __future__ import annotations

from pathlib import Path

from app.config import AppConfig
from app.context.transcript_manager import SessionManager


MODE_INSTRUCTIONS = {
    "roleplay": "Respond in character. Give the character's natural next words or actions, concise enough to use immediately during the session.",
    "tactics": "Based on the character's abilities, equipment, and current situation, give the strongest tactical options available right now. Keep it concise.",
    "knowledge": "Based only on what the character knows, explain what they would know or reasonably recognize. Separate established knowledge from suspicion.",
    "questions": "Give the best questions the character should ask next based on their personality, goals, and current knowledge.",
}


class PromptBuilder:
    def __init__(self, session: SessionManager, config: AppConfig, character_dir: Path) -> None:
        self.session, self.config, self.character_dir = session, config, character_dir

    def build(self, mode: str) -> str:
        if mode not in MODE_INSTRUCTIONS:
            raise ValueError(f"Unknown prompt mode: {mode}")
        parts = ["CURRENT SCENE DIALOGUE"]
        dialogue = self.session.current_scene_tail(self.config.context.scene_dialogue_words)
        if dialogue:
            parts.append("\n".join(entry.display() for entry in dialogue))
        else:
            parts.append("No dialogue captured in this scene yet.")
        if self.config.character.include_summary_in_prompt:
            summary = self._character_summary()
            if summary:
                parts += ["IMPORTANT CHARACTER REFERENCE", summary]
        notes = self._notes_without_title()
        if notes:
            parts += ["IMPORTANT SESSION NOTES", notes]
        parts.append(MODE_INSTRUCTIONS[mode])
        return self._limit_words("\n\n".join(parts), mode)

    def _notes_without_title(self) -> str:
        return "\n".join(line for line in self.session.notes().splitlines() if line.strip() and not line.startswith("#"))

    def _character_summary(self) -> str:
        for name in ("character_summary.md", "character_summary.txt"):
            path = self.character_dir / name
            if path.exists():
                return path.read_text(encoding="utf-8")
        return ""

    def _limit_words(self, prompt: str, mode: str) -> str:
        words = prompt.split()
        maximum = self.config.context.max_prompt_words
        if len(words) <= maximum:
            return prompt
        instruction = MODE_INSTRUCTIONS[mode]
        return " ".join(words[-(maximum - len(instruction.split())):]) + "\n\n" + instruction
