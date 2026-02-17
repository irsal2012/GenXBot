"""Admin authorization and audit helpers for sensitive endpoints."""

from __future__ import annotations

from threading import Lock
from uuid import uuid4

from fastapi import HTTPException, Request

from app.config import get_settings
from app.schemas import AdminActorContext, AdminAuditEntry


class AdminAuthorizationService:
    """Validates admin tokens and role requirements."""

    def __init__(self) -> None:
        settings = get_settings()
        self._admin_token = settings.admin_api_token.strip()

    @property
    def enabled(self) -> bool:
        return bool(self._admin_token)

    def require(self, request: Request, *, minimum_role: str = "admin") -> AdminActorContext:
        token = request.headers.get("x-admin-token", "").strip()
        actor = request.headers.get("x-admin-actor", "system").strip() or "system"
        role = request.headers.get("x-admin-role", "viewer").strip() or "viewer"

        if not self._admin_token:
            return AdminActorContext(actor=actor, actor_role="admin")

        if token != self._admin_token:
            raise HTTPException(status_code=401, detail="Invalid admin token")

        rank = {"viewer": 0, "executor": 1, "approver": 2, "admin": 3}
        if rank.get(role, -1) < rank.get(minimum_role, 3):
            raise HTTPException(status_code=403, detail="Insufficient admin role")

        return AdminActorContext(actor=actor, actor_role=role)  # type: ignore[arg-type]


class AdminAuditService:
    """Stores enriched admin audit events for sensitive mutations."""

    def __init__(self, *, max_entries: int = 5000) -> None:
        self._lock = Lock()
        self._max_entries = max(max_entries, 1)
        self._entries: list[AdminAuditEntry] = []

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def record(
        self,
        *,
        context: AdminActorContext,
        action: str,
        origin: str,
        trace_id: str,
        before: dict,
        after: dict,
    ) -> AdminAuditEntry:
        entry = AdminAuditEntry(
            id=f"admin_audit_{uuid4().hex[:8]}",
            actor=context.actor,
            actor_role=context.actor_role,
            action=action,
            origin=origin,
            trace_id=trace_id,
            before=before,
            after=after,
        )
        with self._lock:
            self._entries.append(entry)
            overflow = len(self._entries) - self._max_entries
            if overflow > 0:
                del self._entries[:overflow]
        return entry

    def list_entries(self) -> list[AdminAuditEntry]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
