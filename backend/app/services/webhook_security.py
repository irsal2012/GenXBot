"""Webhook signature verification and replay protection."""

from __future__ import annotations

import hashlib
import hmac
import time
from threading import Lock


class WebhookSecurityService:
    """Validates signed webhook headers and prevents replay."""

    def __init__(
        self,
        *,
        enabled: bool,
        slack_secret: str,
        telegram_secret: str,
        slack_secrets: list[str] | None = None,
        telegram_secrets: list[str] | None = None,
        replay_window_seconds: int,
    ) -> None:
        self._enabled = enabled
        self._slack_secrets = [s for s in (slack_secrets or []) if s]
        self._telegram_secrets = [s for s in (telegram_secrets or []) if s]
        if slack_secret:
            self._slack_secrets.insert(0, slack_secret)
        if telegram_secret:
            self._telegram_secrets.insert(0, telegram_secret)
        self._replay_window_seconds = replay_window_seconds
        self._seen_events: dict[str, int] = {}
        self._lock = Lock()

    def verify(self, *, channel: str, headers: dict[str, str]) -> None:
        if not self._enabled:
            return

        channel_key = channel.strip().lower()
        now = int(time.time())

        ts_raw = headers.get("x-genx-timestamp")
        event_id = headers.get("x-genx-event-id")
        signature = headers.get("x-genx-signature")
        if not ts_raw or not event_id or not signature:
            raise ValueError("Missing required webhook security headers")

        try:
            ts = int(ts_raw)
        except ValueError as exc:
            raise ValueError("Invalid x-genx-timestamp") from exc

        if abs(now - ts) > self._replay_window_seconds:
            raise ValueError("Webhook timestamp outside replay window")

        secrets = self._slack_secrets if channel_key == "slack" else self._telegram_secrets
        if not secrets:
            raise ValueError("Webhook secret not configured for channel")

        base = f"{ts}:{event_id}".encode("utf-8")
        matched = False
        for secret in secrets:
            expected = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, signature):
                matched = True
                break
        if not matched:
            raise ValueError("Invalid webhook signature")

        if channel_key == "telegram" and self._telegram_secrets:
            token = headers.get("x-telegram-bot-api-secret-token", "")
            if token and token not in self._telegram_secrets:
                raise ValueError("Invalid Telegram webhook secret token")

        replay_key = f"{channel_key}:{event_id}"
        with self._lock:
            existing = self._seen_events.get(replay_key)
            if existing is not None:
                raise ValueError("Replay detected for webhook event")

            self._seen_events[replay_key] = ts
            cutoff = now - self._replay_window_seconds
            self._seen_events = {
                key: value for key, value in self._seen_events.items() if value >= cutoff
            }
