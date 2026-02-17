"""In-memory channel conversation/session tracking."""

from __future__ import annotations

import sqlite3
from threading import Lock
from pathlib import Path

from app.schemas import ChannelSessionSnapshot


class ChannelSessionService:
    """Tracks latest run context by channel conversation key."""

    def __init__(self, db_path: str | None = None) -> None:
        self._lock = Lock()
        self._latest_run_by_session: dict[str, str] = {}
        self._run_ids_by_session: dict[str, list[str]] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path:
            db_file = Path(db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_file), check_same_thread=False)
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS channel_sessions (
                    session_key TEXT PRIMARY KEY,
                    latest_run_id TEXT,
                    run_ids_csv TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def build_session_key(
        self,
        *,
        channel: str,
        channel_id: str,
        thread_id: str | None,
        user_id: str,
    ) -> str:
        thread_or_user = thread_id or f"dm:{user_id}"
        return f"{channel}:{channel_id}:{thread_or_user}"

    def attach_run(self, session_key: str, run_id: str) -> None:
        with self._lock:
            if self._conn:
                existing = self._conn.execute(
                    "SELECT run_ids_csv FROM channel_sessions WHERE session_key = ?",
                    (session_key,),
                ).fetchone()
                run_ids = []
                if existing and existing[0]:
                    run_ids = [v for v in existing[0].split(",") if v]
                run_ids.append(run_id)
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO channel_sessions (session_key, latest_run_id, run_ids_csv)
                    VALUES (?, ?, ?)
                    """,
                    (session_key, run_id, ",".join(run_ids)),
                )
                self._conn.commit()
                return

            self._latest_run_by_session[session_key] = run_id
            self._run_ids_by_session.setdefault(session_key, []).append(run_id)

    def get_latest_run(self, session_key: str) -> str | None:
        with self._lock:
            if self._conn:
                row = self._conn.execute(
                    "SELECT latest_run_id FROM channel_sessions WHERE session_key = ?",
                    (session_key,),
                ).fetchone()
                return row[0] if row and row[0] else None
            return self._latest_run_by_session.get(session_key)

    def get_runs(self, session_key: str) -> list[str]:
        with self._lock:
            if self._conn:
                row = self._conn.execute(
                    "SELECT run_ids_csv FROM channel_sessions WHERE session_key = ?",
                    (session_key,),
                ).fetchone()
                if not row or not row[0]:
                    return []
                return [v for v in row[0].split(",") if v]
            return list(self._run_ids_by_session.get(session_key, []))

    def list_snapshots(self) -> list[ChannelSessionSnapshot]:
        with self._lock:
            if self._conn:
                rows = self._conn.execute(
                    "SELECT session_key, latest_run_id, run_ids_csv FROM channel_sessions ORDER BY session_key"
                ).fetchall()
                return [
                    ChannelSessionSnapshot(
                        session_key=row[0],
                        latest_run_id=row[1],
                        run_ids=[v for v in (row[2] or "").split(",") if v],
                    )
                    for row in rows
                ]

            snapshots: list[ChannelSessionSnapshot] = []
            for session_key in sorted(self._run_ids_by_session.keys()):
                snapshots.append(
                    ChannelSessionSnapshot(
                        session_key=session_key,
                        latest_run_id=self._latest_run_by_session.get(session_key),
                        run_ids=list(self._run_ids_by_session.get(session_key, [])),
                    )
                )
            return snapshots
