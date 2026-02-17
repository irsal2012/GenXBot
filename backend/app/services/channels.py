"""Channel adapters for normalizing inbound provider payloads."""

from __future__ import annotations

from typing import Optional

from app.schemas import ChannelMessageEvent


def parse_channel_event(channel: str, event_type: str, payload: dict) -> ChannelMessageEvent:
    """Normalize provider payloads into ChannelMessageEvent."""
    channel_key = channel.strip().lower()
    if channel_key == "slack":
        return _parse_slack_event(event_type=event_type, payload=payload)
    if channel_key == "telegram":
        return _parse_telegram_event(event_type=event_type, payload=payload)
    raise ValueError(f"Unsupported channel: {channel}")


def _parse_slack_event(event_type: str, payload: dict) -> ChannelMessageEvent:
    event = payload.get("event", payload)
    user_id = event.get("user")
    channel_id = event.get("channel")
    text = event.get("text")
    if not user_id or not channel_id or not text:
        raise ValueError("Invalid Slack payload: missing user/channel/text")

    return ChannelMessageEvent(
        channel="slack",
        event_type=event_type or event.get("type") or "message",
        user_id=str(user_id),
        channel_id=str(channel_id),
        text=str(text),
        message_id=str(event.get("ts")) if event.get("ts") is not None else None,
        thread_id=str(event.get("thread_ts")) if event.get("thread_ts") is not None else None,
    )


def _parse_telegram_event(event_type: str, payload: dict) -> ChannelMessageEvent:
    message = payload.get("message", payload)
    from_obj = message.get("from", {})
    chat_obj = message.get("chat", {})
    user_id = from_obj.get("id")
    channel_id = chat_obj.get("id")
    text = message.get("text")
    if user_id is None or channel_id is None or not text:
        raise ValueError("Invalid Telegram payload: missing from.id/chat.id/text")

    return ChannelMessageEvent(
        channel="telegram",
        event_type=event_type or "message",
        user_id=str(user_id),
        channel_id=str(channel_id),
        text=str(text),
        message_id=str(message.get("message_id")) if message.get("message_id") is not None else None,
        thread_id=str(message.get("message_thread_id"))
        if message.get("message_thread_id") is not None
        else None,
    )


def parse_channel_command(text: str) -> tuple[Optional[str], str]:
    """Parse slash-style chat commands.

    Returns (command, args). If no recognized command, command is None.
    """
    cleaned = (text or "").strip()
    if not cleaned.startswith("/"):
        return None, cleaned

    parts = cleaned.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    if cmd in {"/run", "/status", "/approve", "/reject"}:
        return cmd[1:], args
    return None, cleaned
