"""Channel trust policy and pairing-code management for inbound messages."""

from __future__ import annotations

import sqlite3
from threading import Lock
from uuid import uuid4
from pathlib import Path

from app.schemas import ChannelTrustPolicy, PendingPairingCode


class ChannelTrustService:
    """In-memory trust policy and pairing workflow for channels."""

    def __init__(self, db_path: str | None = None) -> None:
        self._lock = Lock()
        self._policies: dict[str, ChannelTrustPolicy] = {
            "slack": ChannelTrustPolicy(channel="slack", dm_policy="pairing", allow_from=[]),
            "telegram": ChannelTrustPolicy(channel="telegram", dm_policy="pairing", allow_from=[]),
        }
        self._paired_users: dict[str, set[str]] = {"slack": set(), "telegram": set()}
        self._pending_codes: dict[str, PendingPairingCode] = {}
        self._conn: sqlite3.Connection | None = None

        if db_path:
            db_file = Path(db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_file), check_same_thread=False)
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS channel_trust_policy (
                    channel TEXT PRIMARY KEY,
                    dm_policy TEXT NOT NULL,
                    allow_from_csv TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS channel_paired_users (
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    PRIMARY KEY (channel, user_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS channel_pending_codes (
                    channel TEXT NOT NULL,
                    code TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (channel, code)
                )
                """
            )
            self._conn.commit()
            self._bootstrap_defaults()

    def _bootstrap_defaults(self) -> None:
        if not self._conn:
            return
        for channel in ("slack", "telegram"):
            self._conn.execute(
                """
                INSERT OR IGNORE INTO channel_trust_policy (channel, dm_policy, allow_from_csv)
                VALUES (?, ?, ?)
                """,
                (channel, "pairing", ""),
            )
        self._conn.commit()

    def get_policy(self, channel: str) -> ChannelTrustPolicy:
        channel_key = channel.strip().lower()
        with self._lock:
            if self._conn:
                row = self._conn.execute(
                    "SELECT dm_policy, allow_from_csv FROM channel_trust_policy WHERE channel = ?",
                    (channel_key,),
                ).fetchone()
                if not row:
                    raise ValueError(f"Unsupported channel: {channel}")
                allow_from = [v for v in (row[1] or "").split(",") if v]
                return ChannelTrustPolicy(channel=channel_key, dm_policy=row[0], allow_from=allow_from)

            policy = self._policies.get(channel_key)
            if not policy:
                raise ValueError(f"Unsupported channel: {channel}")
            return policy

    def set_policy(self, channel: str, dm_policy: str, allow_from: list[str]) -> ChannelTrustPolicy:
        channel_key = channel.strip().lower()
        with self._lock:
            if self._conn:
                if channel_key not in {"slack", "telegram"}:
                    raise ValueError(f"Unsupported channel: {channel}")
                cleaned = [str(v) for v in allow_from]
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO channel_trust_policy (channel, dm_policy, allow_from_csv)
                    VALUES (?, ?, ?)
                    """,
                    (channel_key, dm_policy, ",".join(cleaned)),
                )
                self._conn.commit()
                return ChannelTrustPolicy(channel=channel_key, dm_policy=dm_policy, allow_from=cleaned)

            if channel_key not in self._policies:
                raise ValueError(f"Unsupported channel: {channel}")
            policy = ChannelTrustPolicy(
                channel=channel_key,
                dm_policy=dm_policy,
                allow_from=[str(v) for v in allow_from],
            )
            self._policies[channel_key] = policy
            return policy

    def is_trusted(self, channel: str, user_id: str) -> bool:
        channel_key = channel.strip().lower()
        uid = str(user_id)
        with self._lock:
            if self._conn:
                row = self._conn.execute(
                    "SELECT dm_policy, allow_from_csv FROM channel_trust_policy WHERE channel = ?",
                    (channel_key,),
                ).fetchone()
                if not row:
                    return False
                policy = ChannelTrustPolicy(
                    channel=channel_key,
                    dm_policy=row[0],
                    allow_from=[v for v in (row[1] or "").split(",") if v],
                )
                if "*" in policy.allow_from or uid in policy.allow_from:
                    return True
                if policy.dm_policy == "open":
                    return not policy.allow_from
                row = self._conn.execute(
                    "SELECT 1 FROM channel_paired_users WHERE channel = ? AND user_id = ?",
                    (channel_key, uid),
                ).fetchone()
                return row is not None

            policy = self._policies.get(channel_key)
            if not policy:
                return False

            if "*" in policy.allow_from or uid in policy.allow_from:
                return True

            if policy.dm_policy == "open":
                return not policy.allow_from

            return uid in self._paired_users.get(channel_key, set())

    def issue_pairing_code(self, channel: str, user_id: str) -> PendingPairingCode:
        channel_key = channel.strip().lower()
        uid = str(user_id)
        with self._lock:
            if self._conn:
                existing = self._conn.execute(
                    "SELECT code, created_at FROM channel_pending_codes WHERE channel = ? AND user_id = ?",
                    (channel_key, uid),
                ).fetchone()
                if existing:
                    return PendingPairingCode(
                        channel=channel_key,
                        code=existing[0],
                        user_id=uid,
                        created_at=existing[1],
                    )

                pending = PendingPairingCode(channel=channel_key, code=uuid4().hex[:6].upper(), user_id=uid)
                self._conn.execute(
                    """
                    INSERT INTO channel_pending_codes (channel, code, user_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (channel_key, pending.code, pending.user_id, pending.created_at),
                )
                self._conn.commit()
                return pending

            for pending in self._pending_codes.values():
                if pending.channel == channel_key and pending.user_id == uid:
                    return pending

            code = uuid4().hex[:6].upper()
            pending = PendingPairingCode(channel=channel_key, code=code, user_id=uid)
            self._pending_codes[f"{channel_key}:{code}"] = pending
            return pending

    def approve_pairing_code(self, channel: str, code: str) -> str | None:
        channel_key = channel.strip().lower()
        code_key = f"{channel_key}:{code.strip().upper()}"
        with self._lock:
            if self._conn:
                row = self._conn.execute(
                    "SELECT user_id FROM channel_pending_codes WHERE channel = ? AND code = ?",
                    (channel_key, code.strip().upper()),
                ).fetchone()
                if not row:
                    return None
                user_id = row[0]
                self._conn.execute(
                    "DELETE FROM channel_pending_codes WHERE channel = ? AND code = ?",
                    (channel_key, code.strip().upper()),
                )
                self._conn.execute(
                    "INSERT OR IGNORE INTO channel_paired_users (channel, user_id) VALUES (?, ?)",
                    (channel_key, user_id),
                )
                self._conn.commit()
                return user_id

            pending = self._pending_codes.pop(code_key, None)
            if not pending:
                return None
            self._paired_users.setdefault(channel_key, set()).add(pending.user_id)
            return pending.user_id

    def list_pending_codes(self, channel: str) -> list[PendingPairingCode]:
        channel_key = channel.strip().lower()
        with self._lock:
            if self._conn:
                rows = self._conn.execute(
                    """
                    SELECT code, user_id, created_at
                    FROM channel_pending_codes
                    WHERE channel = ?
                    ORDER BY created_at ASC
                    """,
                    (channel_key,),
                ).fetchall()
                return [
                    PendingPairingCode(
                        channel=channel_key,
                        code=row[0],
                        user_id=row[1],
                        created_at=row[2],
                    )
                    for row in rows
                ]

            return [p for p in self._pending_codes.values() if p.channel == channel_key]
