"""Outbound channel message helpers (formatting + stubs)."""

from __future__ import annotations

import httpx

from app.schemas import RunSession


def format_outbound_run_created(run: RunSession) -> str:
    return (
        f"✅ Run created: {run.id}\n"
        f"Goal: {run.goal}\n"
        f"Status: {run.status}\n"
        "Approve all actions now? (yes/no)\n"
        "Reply 'yes' to approve all pending actions, or 'no' to review manually with /status."
    )


def format_outbound_status(run: RunSession) -> str:
    pending = [a for a in run.pending_actions if a.status == "pending"]
    pending_lines = "\n".join(
        f"- action_id: {action.id}\n  type: {action.action_type}\n  summary: {action.description}"
        for action in pending
    )
    pending_section = f"\nPending action details:\n{pending_lines}" if pending_lines else ""
    return (
        f"📌 Run {run.id}\n"
        f"Status: {run.status}\n"
        f"Pending actions: {len(pending)}\n"
        f"Timeline events: {len(run.timeline)}"
        f"{pending_section}"
    )


def format_outbound_action_decision(run: RunSession, approved: bool) -> str:
    decision = "approved" if approved else "rejected"
    return f"🧾 Action {decision}. Run {run.id} is now {run.status}."


class ChannelOutboundService:
    """Delivers outbound messages to channel providers when enabled."""

    def __init__(
        self,
        *,
        enabled: bool,
        slack_webhook_url: str,
        telegram_bot_token: str,
        telegram_api_base_url: str,
    ) -> None:
        self._enabled = enabled
        self._slack_webhook_url = slack_webhook_url.strip()
        self._telegram_bot_token = telegram_bot_token.strip()
        self._telegram_api_base_url = telegram_api_base_url.rstrip("/")

    def send(self, *, channel: str, channel_id: str, text: str, thread_id: str | None = None) -> str:
        if not self._enabled:
            return "skipped:disabled"

        try:
            if channel == "slack":
                return self._send_slack(channel_id=channel_id, text=text, thread_id=thread_id)
            if channel == "telegram":
                return self._send_telegram(channel_id=channel_id, text=text, thread_id=thread_id)
            return "skipped:unsupported_channel"
        except Exception as exc:  # pragma: no cover - defensive
            return f"failed:{exc}"

    def _send_slack(self, *, channel_id: str, text: str, thread_id: str | None) -> str:
        if not self._slack_webhook_url:
            return "skipped:slack_webhook_not_configured"
        payload = {"text": text, "channel": channel_id}
        if thread_id:
            payload["thread_ts"] = thread_id
        with httpx.Client(timeout=5.0) as client:
            res = client.post(self._slack_webhook_url, json=payload)
            res.raise_for_status()
        return "sent:slack"

    def _send_telegram(self, *, channel_id: str, text: str, thread_id: str | None) -> str:
        if not self._telegram_bot_token:
            return "skipped:telegram_token_not_configured"
        url = f"{self._telegram_api_base_url}/bot{self._telegram_bot_token}/sendMessage"
        payload: dict[str, str] = {"chat_id": channel_id, "text": text}
        if thread_id:
            payload["message_thread_id"] = thread_id
        with httpx.Client(timeout=5.0) as client:
            res = client.post(url, json=payload)
            res.raise_for_status()
        return "sent:telegram"
