"""Run store with optional SQLite persistence for GenXBot."""

from __future__ import annotations

from collections.abc import Iterable
import sqlite3
from typing import Optional
from pathlib import Path

from app.schemas import RunSession


class RunStore:
    """Store for run sessions (in-memory by default, SQLite optional)."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._runs: dict[str, RunSession] = {}
        self._conn: Optional[sqlite3.Connection] = None
        if db_path:
            db_file = Path(db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_file), check_same_thread=False)
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def create(self, run: RunSession) -> RunSession:
        if self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO runs (id, payload_json, updated_at) VALUES (?, ?, ?)",
                (run.id, run.model_dump_json(), run.updated_at),
            )
            self._conn.commit()
        else:
            self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> Optional[RunSession]:
        if self._conn:
            row = self._conn.execute(
                "SELECT payload_json FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                return None
            return RunSession.model_validate_json(row[0])
        return self._runs.get(run_id)

    def update(self, run: RunSession) -> RunSession:
        if self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO runs (id, payload_json, updated_at) VALUES (?, ?, ?)",
                (run.id, run.model_dump_json(), run.updated_at),
            )
            self._conn.commit()
        else:
            self._runs[run.id] = run
        return run

    def list_runs(self) -> Iterable[RunSession]:
        if self._conn:
            rows = self._conn.execute(
                "SELECT payload_json FROM runs ORDER BY updated_at DESC"
            ).fetchall()
            return [RunSession.model_validate_json(row[0]) for row in rows]
        return self._runs.values()
