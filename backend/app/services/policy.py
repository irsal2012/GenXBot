"""Safety and approval policy helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.schemas import ProposedAction


class SafetyPolicy:
    """Very small policy engine for prototype approval gates."""

    SAFE_COMMAND_PREFIXES = (
        "pytest",
        "python -m pytest",
        "python3 -m pytest",
        "ruff check",
        "ruff format",
        "npm test",
        "npm run lint",
        "npm run build",
    )

    BLOCKED_COMMAND_TOKENS = (
        " rm ",
        "rm -rf",
        "sudo",
        "chmod 777",
        "mkfs",
        "shutdown",
        "reboot",
        ":(){",
    )

    ALLOWED_EDIT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml"}
    ALLOWED_COMMAND_PATTERNS = (
        ("pytest",),
        ("python", "-m", "pytest"),
        ("python3", "-m", "pytest"),
        ("ruff", "check"),
        ("ruff", "format"),
        ("npm", "test"),
        ("npm", "run", "lint"),
        ("npm", "run", "build"),
    )
    DISALLOWED_ARG_TOKENS = {"&&", "||", ";", "|", ">", ">>", "<", "2>", "&"}
    APPROVAL_ROLES = {"approver", "admin"}

    def is_safe_command(self, command: str) -> bool:
        cleaned = command.strip()
        return any(cleaned.startswith(prefix) for prefix in self.SAFE_COMMAND_PREFIXES)

    def requires_approval(self, action: ProposedAction) -> bool:
        if action.action_type == "edit":
            return True
        if action.action_type == "command":
            return not (action.command and self.is_safe_command(action.command))
        return True

    def is_command_allowed(self, command: str) -> bool:
        lowered = f" {command.strip().lower()} "
        return not any(token in lowered for token in self.BLOCKED_COMMAND_TOKENS)

    def is_command_spec_allowed(self, argv: Sequence[str]) -> bool:
        if not argv:
            return False
        if any(token in self.DISALLOWED_ARG_TOKENS for token in argv):
            return False
        return any(tuple(argv[: len(pattern)]) == pattern for pattern in self.ALLOWED_COMMAND_PATTERNS)

    def is_edit_path_allowed(self, workspace_root: str, file_path: str) -> bool:
        root = Path(workspace_root).resolve()
        target = Path(file_path).resolve()
        if root not in target.parents and root != target:
            return False
        return target.suffix.lower() in self.ALLOWED_EDIT_SUFFIXES

    def can_approve(self, actor_role: str) -> bool:
        return actor_role in self.APPROVAL_ROLES
