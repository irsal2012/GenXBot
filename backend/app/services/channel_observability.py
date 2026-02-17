"""Lightweight observability + metrics for channel workflows."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from uuid import uuid4

from app.schemas import ChannelMetricsSnapshot


class ChannelObservabilityService:
    """Tracks channel counters and issues trace IDs."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._metrics = ChannelMetricsSnapshot()

    def new_trace_id(self) -> str:
        return f"trace_{uuid4().hex[:12]}"

    def record_inbound(self, *, channel: str, command: str | None = None) -> None:
        with self._lock:
            self._metrics.total_inbound_events += 1
            self._metrics.per_channel_inbound[channel] = self._metrics.per_channel_inbound.get(channel, 0) + 1
            if command:
                self._metrics.command_counts[command] = self._metrics.command_counts.get(command, 0) + 1

    def record_outbound(self, *, channel: str, delivery_status: str) -> None:
        with self._lock:
            self._metrics.total_outbound_attempts += 1
            if delivery_status.startswith("sent:"):
                self._metrics.total_outbound_success += 1
                self._metrics.per_channel_outbound_success[channel] = (
                    self._metrics.per_channel_outbound_success.get(channel, 0) + 1
                )
            elif delivery_status.startswith("failed:"):
                self._metrics.total_outbound_failed += 1

    def record_replay_blocked(self) -> None:
        with self._lock:
            self._metrics.total_replays_blocked += 1

    def snapshot(self) -> ChannelMetricsSnapshot:
        with self._lock:
            return ChannelMetricsSnapshot(
                total_inbound_events=self._metrics.total_inbound_events,
                total_outbound_attempts=self._metrics.total_outbound_attempts,
                total_outbound_success=self._metrics.total_outbound_success,
                total_outbound_failed=self._metrics.total_outbound_failed,
                total_replays_blocked=self._metrics.total_replays_blocked,
                command_counts=dict(self._metrics.command_counts),
                per_channel_inbound=dict(self._metrics.per_channel_inbound),
                per_channel_outbound_success=dict(self._metrics.per_channel_outbound_success),
            )
