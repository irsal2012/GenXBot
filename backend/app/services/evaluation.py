"""Evaluation metrics service for GenXBot runs."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from app.schemas import EvaluationMetrics, LatencyMetrics, RunSession, SafetyMetrics


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    values = sorted(values)
    idx = int(round((len(values) - 1) * q))
    idx = max(0, min(idx, len(values) - 1))
    return float(values[idx])


def compute_evaluation_metrics(runs: Iterable[RunSession]) -> EvaluationMetrics:
    """Compute aggregate success, latency, and safety metrics across runs."""
    run_list = list(runs)
    total_runs = len(run_list)

    completed_runs = sum(1 for r in run_list if r.status == "completed")
    failed_runs = sum(1 for r in run_list if r.status == "failed")
    active_runs = sum(1 for r in run_list if r.status in {"created", "awaiting_approval", "running"})
    terminal_runs = completed_runs + failed_runs

    run_success_rate = (completed_runs / terminal_runs) if terminal_runs else 0.0
    run_completion_rate = (completed_runs / total_runs) if total_runs else 0.0

    durations: list[float] = []
    total_actions = 0
    approved_actions = 0
    rejected_actions = 0
    executed_actions = 0
    command_actions = 0
    safe_command_actions = 0
    blocked_actions = 0

    for run in run_list:
        created = _parse_iso(run.created_at)
        updated = _parse_iso(run.updated_at)
        if created and updated:
            delta = (updated - created).total_seconds()
            if delta >= 0:
                durations.append(delta)

        blocked_actions += sum(1 for evt in run.timeline if evt.event == "action_blocked")

        for action in run.pending_actions:
            total_actions += 1
            if action.status in {"approved", "executed"}:
                approved_actions += 1
            if action.status == "rejected":
                rejected_actions += 1
            if action.status == "executed":
                executed_actions += 1
            if action.action_type == "command":
                command_actions += 1
                if action.safe:
                    safe_command_actions += 1

    latency = LatencyMetrics(
        samples=len(durations),
        average_seconds=(sum(durations) / len(durations)) if durations else 0.0,
        p50_seconds=_percentile(durations, 0.50),
        p95_seconds=_percentile(durations, 0.95),
        max_seconds=max(durations) if durations else 0.0,
    )

    safety = SafetyMetrics(
        total_actions=total_actions,
        approved_actions=approved_actions,
        rejected_actions=rejected_actions,
        executed_actions=executed_actions,
        blocked_actions=blocked_actions,
        command_actions=command_actions,
        safe_command_actions=safe_command_actions,
        approval_rate=(approved_actions / total_actions) if total_actions else 0.0,
        rejection_rate=(rejected_actions / total_actions) if total_actions else 0.0,
        execution_rate_of_approved=(executed_actions / approved_actions) if approved_actions else 0.0,
        safe_command_ratio=(safe_command_actions / command_actions) if command_actions else 0.0,
    )

    return EvaluationMetrics(
        total_runs=total_runs,
        completed_runs=completed_runs,
        failed_runs=failed_runs,
        active_runs=active_runs,
        terminal_runs=terminal_runs,
        run_success_rate=run_success_rate,
        run_completion_rate=run_completion_rate,
        latency=latency,
        safety=safety,
    )
