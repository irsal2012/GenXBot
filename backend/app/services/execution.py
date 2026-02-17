"""Execution helpers for approved actions (command + edit)."""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import List, Tuple

from app.schemas import ProposedAction
from app.services.policy import SafetyPolicy


class ActionExecutionError(Exception):
    """Raised when an approved action cannot be executed safely."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ActionExecutor:
    """Execute approved actions with guardrails."""

    def __init__(self, policy: SafetyPolicy, retry_attempts: int = 2, retry_backoff_seconds: float = 0.2) -> None:
        self._policy = policy
        self._retry_attempts = max(retry_attempts, 1)
        self._retry_backoff_seconds = max(retry_backoff_seconds, 0.0)

    def execute(self, action: ProposedAction, workspace_root: str) -> Tuple[str, str]:
        """Execute approved action and return artifact kind + content."""
        if action.action_type == "command":
            return "command_output", self._execute_with_retry(self._execute_command, action, workspace_root)
        if action.action_type == "edit":
            return "diff", self._execute_with_retry(self._execute_edit, action, workspace_root)
        raise ActionExecutionError(f"Unsupported action type: {action.action_type}")

    def _execute_with_retry(self, fn, action: ProposedAction, workspace_root: str) -> str:
        last_exc: ActionExecutionError | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                return fn(action, workspace_root)
            except ActionExecutionError as exc:
                last_exc = exc
                if not exc.retryable or attempt >= self._retry_attempts:
                    raise
                time.sleep(self._retry_backoff_seconds)
        if last_exc:
            raise last_exc
        raise ActionExecutionError("Execution failed unexpectedly")

    def _execute_command(self, action: ProposedAction, workspace_root: str) -> str:
        command = (action.command or "").strip()
        if not command:
            raise ActionExecutionError("Missing command for command action")
        if not self._policy.is_command_allowed(command):
            raise ActionExecutionError("Command blocked by safety policy")

        argv = shlex.split(command)
        if not argv:
            raise ActionExecutionError("Command parsed to empty argv")
        if not self._policy.is_command_spec_allowed(argv):
            raise ActionExecutionError("Command is not in allowlisted shell-free patterns")

        try:
            completed = subprocess.run(
                argv,
                shell=False,
                cwd=workspace_root,
                text=True,
                capture_output=True,
                timeout=90,
            )
        except FileNotFoundError as exc:
            raise ActionExecutionError(f"Command executable not found: {argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ActionExecutionError("Command timed out after 90 seconds", retryable=True) from exc
        output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
        output = output.strip() or "(no output)"
        return f"$ {command}\nexit_code={completed.returncode}\n\n{output}"

    def _execute_edit(self, action: ProposedAction, workspace_root: str) -> str:
        file_path = action.file_path or ""
        if not file_path:
            raise ActionExecutionError("Missing file_path for edit action")
        if not self._policy.is_edit_path_allowed(workspace_root=workspace_root, file_path=file_path):
            raise ActionExecutionError("Edit path is outside allowed workspace/suffix policy")

        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        patch_text = (action.patch or "").strip()
        if not patch_text:
            raise ActionExecutionError("Missing patch content for edit action")

        before = target.read_text(encoding="utf-8") if target.exists() else ""

        if self._looks_like_unified_diff(patch_text):
            after = self._apply_unified_diff(before, patch_text)
        elif patch_text.startswith("FULL_FILE_CONTENT:\n"):
            after = patch_text.replace("FULL_FILE_CONTENT:\n", "", 1)
        else:
            raise ActionExecutionError(
                "Unsupported patch format. Use unified diff or FULL_FILE_CONTENT marker."
            )

        target.write_text(after, encoding="utf-8")
        return (
            f"Applied edit to {target}\n"
            f"--- before ({len(before)} chars) ---\n{before[:500]}\n"
            f"--- after ({len(after)} chars) ---\n{after[:500]}"
        )

    @staticmethod
    def _looks_like_unified_diff(patch_text: str) -> bool:
        return "@@" in patch_text and "\n--- " in f"\n{patch_text}" and "\n+++ " in f"\n{patch_text}"

    @staticmethod
    def _apply_unified_diff(original: str, patch_text: str) -> str:
        """Apply a minimal unified diff to original text."""
        old_lines = original.splitlines()
        patch_lines = patch_text.splitlines()
        out_lines: List[str] = []

        i = 0
        src_idx = 0
        hunk_re = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")

        while i < len(patch_lines):
            line = patch_lines[i]
            if line.startswith("--- ") or line.startswith("+++ "):
                i += 1
                continue

            if not line.startswith("@@"):
                i += 1
                continue

            match = hunk_re.match(line)
            if not match:
                raise ActionExecutionError("Invalid unified diff hunk header")

            old_start = int(match.group(1))
            copy_until = max(old_start - 1, 0)
            while src_idx < copy_until and src_idx < len(old_lines):
                out_lines.append(old_lines[src_idx])
                src_idx += 1

            i += 1
            while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
                hunk_line = patch_lines[i]
                if not hunk_line:
                    token = " "
                    payload = ""
                else:
                    token = hunk_line[0]
                    payload = hunk_line[1:]

                if token == " ":
                    if src_idx >= len(old_lines) or old_lines[src_idx] != payload:
                        raise ActionExecutionError("Unified diff context mismatch")
                    out_lines.append(payload)
                    src_idx += 1
                elif token == "-":
                    if src_idx >= len(old_lines) or old_lines[src_idx] != payload:
                        raise ActionExecutionError("Unified diff removal mismatch")
                    src_idx += 1
                elif token == "+":
                    out_lines.append(payload)
                elif token == "\\":
                    # e.g. "\ No newline at end of file"
                    pass
                else:
                    raise ActionExecutionError(f"Unsupported unified diff token: {token}")
                i += 1

        while src_idx < len(old_lines):
            out_lines.append(old_lines[src_idx])
            src_idx += 1

        if original.endswith("\n"):
            return "\n".join(out_lines) + "\n"
        return "\n".join(out_lines)
