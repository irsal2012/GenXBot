"""Pydantic schemas for GenXBot autonomous coding workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunTaskRequest(BaseModel):
    goal: str = Field(..., min_length=3)
    repo_path: str = Field(..., min_length=1)
    context: Optional[str] = None
    requested_by: str = "anonymous"
    recipe_id: Optional[str] = None
    recipe_inputs: dict[str, str] = Field(default_factory=dict)
    recipe_actions: list["RecipeActionTemplate"] = Field(default_factory=list)


class RecipeActionTemplate(BaseModel):
    action_type: Literal["command", "edit"]
    description: str
    command: Optional[str] = None
    file_path: Optional[str] = None
    patch: Optional[str] = None


class RecipeDefinition(BaseModel):
    id: str
    name: str
    description: str
    goal_template: str
    context_template: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    action_templates: list[RecipeActionTemplate] = Field(default_factory=list)
    enabled: bool = True


class RecipeCreateRequest(BaseModel):
    id: str = Field(..., min_length=2)
    name: str = Field(..., min_length=2)
    description: str = ""
    goal_template: str = Field(..., min_length=3)
    context_template: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    action_templates: list[RecipeActionTemplate] = Field(default_factory=list)


class RecipeListResponse(BaseModel):
    recipes: list[RecipeDefinition] = Field(default_factory=list)


class ConnectorTriggerRequest(BaseModel):
    connector: Literal["github", "jira", "slack"]
    event_type: str
    payload: dict
    default_repo_path: Optional[str] = None


class ConnectorTriggerResponse(BaseModel):
    connector: Literal["github", "jira", "slack"]
    event_type: str
    run: "RunSession"


class ChannelMessageEvent(BaseModel):
    channel: Literal["slack", "telegram"]
    event_type: str
    user_id: str
    channel_id: str
    text: str
    message_id: Optional[str] = None
    thread_id: Optional[str] = None


class ChannelInboundRequest(BaseModel):
    channel: Literal["slack", "telegram"]
    event_type: str
    payload: dict
    default_repo_path: Optional[str] = None


class ChannelInboundResponse(BaseModel):
    channel: Literal["slack", "telegram"]
    event_type: str
    run: Optional["RunSession"] = None
    command: Optional[str] = None
    outbound_text: Optional[str] = None
    outbound_delivery: Optional[str] = None
    session_key: Optional[str] = None
    trace_id: Optional[str] = None


class ChannelSessionSnapshot(BaseModel):
    session_key: str
    latest_run_id: Optional[str] = None
    run_ids: list[str] = Field(default_factory=list)


class ChannelMetricsSnapshot(BaseModel):
    total_inbound_events: int = 0
    total_outbound_attempts: int = 0
    total_outbound_success: int = 0
    total_outbound_failed: int = 0
    total_replays_blocked: int = 0
    command_counts: dict[str, int] = Field(default_factory=dict)
    per_channel_inbound: dict[str, int] = Field(default_factory=dict)
    per_channel_outbound_success: dict[str, int] = Field(default_factory=dict)


class OutboundRetryJob(BaseModel):
    id: str
    channel: Literal["slack", "telegram"]
    channel_id: str
    text: str
    thread_id: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    last_error: Optional[str] = None


class OutboundRetryQueueSnapshot(BaseModel):
    queued: int
    dead_lettered: int
    dead_letters: list[OutboundRetryJob] = Field(default_factory=list)


class QueueHealthSnapshot(BaseModel):
    run_queue_pending: int
    run_worker_alive: bool
    outbound_retry_pending: int
    outbound_retry_dead_lettered: int
    outbound_retry_worker_alive: bool


class IdempotencyCacheSnapshot(BaseModel):
    entries: int
    ttl_seconds: int
    max_entries: int


class AdminAuditSnapshot(BaseModel):
    entries: int
    max_entries: int


class AdminActorContext(BaseModel):
    actor: str
    actor_role: Literal["viewer", "executor", "approver", "admin"]


class AdminAuditEntry(BaseModel):
    id: str = Field(default_factory=lambda: f"admin_audit_{uuid4().hex[:8]}")
    timestamp: str = Field(default_factory=utc_now_iso)
    actor: str
    actor_role: Literal["viewer", "executor", "approver", "admin"]
    action: str
    origin: str
    trace_id: str
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)


class ApproverAllowlistResponse(BaseModel):
    users: list[str] = Field(default_factory=list)


class ApproverAllowlistUpdateRequest(BaseModel):
    users: list[str] = Field(default_factory=list)


class ChannelTrustPolicy(BaseModel):
    channel: Literal["slack", "telegram"]
    dm_policy: Literal["pairing", "open"] = "pairing"
    allow_from: list[str] = Field(default_factory=list)


class ChannelTrustPolicyUpdateRequest(BaseModel):
    dm_policy: Literal["pairing", "open"]
    allow_from: list[str] = Field(default_factory=list)


class ChannelMaintenanceMode(BaseModel):
    channel: Literal["slack", "telegram"]
    enabled: bool = False
    reason: str = ""


class ChannelMaintenanceModeUpdateRequest(BaseModel):
    enabled: bool
    reason: str = ""


class PairingApprovalRequest(BaseModel):
    code: str
    actor: str = "admin"


class PairingApprovalResponse(BaseModel):
    channel: Literal["slack", "telegram"]
    code: str
    approved: bool
    user_id: Optional[str] = None


class PendingPairingCode(BaseModel):
    channel: Literal["slack", "telegram"]
    code: str
    user_id: str
    created_at: str = Field(default_factory=utc_now_iso)


class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: f"step_{uuid4().hex[:8]}")
    title: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    requires_approval: bool = False


class TimelineEvent(BaseModel):
    timestamp: str = Field(default_factory=utc_now_iso)
    agent: str
    event: str
    content: str


class AuditEntry(BaseModel):
    id: str = Field(default_factory=lambda: f"audit_{uuid4().hex[:8]}")
    timestamp: str = Field(default_factory=utc_now_iso)
    actor: str
    actor_role: Literal["viewer", "executor", "approver", "admin"]
    action: str
    detail: str


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: f"artifact_{uuid4().hex[:8]}")
    kind: Literal["plan", "diff", "command_output", "summary"]
    title: str
    content: str


class ProposedAction(BaseModel):
    id: str = Field(default_factory=lambda: f"action_{uuid4().hex[:8]}")
    action_type: Literal["edit", "command"]
    description: str
    safe: bool = False
    status: Literal["pending", "approved", "rejected", "executed"] = "pending"
    command: Optional[str] = None
    file_path: Optional[str] = None
    patch: Optional[str] = None


class RunSession(BaseModel):
    id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:10]}")
    goal: str
    repo_path: str
    sandbox_path: Optional[str] = None
    status: Literal["created", "awaiting_approval", "running", "completed", "failed"] = "created"
    plan_steps: list[PlanStep] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    audit_log: list[AuditEntry] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    pending_actions: list[ProposedAction] = Field(default_factory=list)
    memory_summary: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class QueueJobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    run: Optional[RunSession] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class ApprovalRequest(BaseModel):
    action_id: str
    approve: bool
    comment: Optional[str] = None
    actor: str = "anonymous"
    actor_role: Literal["viewer", "executor", "approver", "admin"] = "viewer"


class RerunFailedStepRequest(BaseModel):
    action_id: Optional[str] = None
    step_id: Optional[str] = None
    comment: Optional[str] = None
    actor: str = "anonymous"
    actor_role: Literal["viewer", "executor", "approver", "admin"] = "viewer"


class LatencyMetrics(BaseModel):
    samples: int = 0
    average_seconds: float = 0.0
    p50_seconds: float = 0.0
    p95_seconds: float = 0.0
    max_seconds: float = 0.0


class SafetyMetrics(BaseModel):
    total_actions: int = 0
    approved_actions: int = 0
    rejected_actions: int = 0
    executed_actions: int = 0
    blocked_actions: int = 0
    command_actions: int = 0
    safe_command_actions: int = 0
    approval_rate: float = 0.0
    rejection_rate: float = 0.0
    execution_rate_of_approved: float = 0.0
    safe_command_ratio: float = 0.0


class EvaluationMetrics(BaseModel):
    generated_at: str = Field(default_factory=utc_now_iso)
    total_runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    active_runs: int = 0
    terminal_runs: int = 0
    run_success_rate: float = 0.0
    run_completion_rate: float = 0.0
    latency: LatencyMetrics = Field(default_factory=LatencyMetrics)
    safety: SafetyMetrics = Field(default_factory=SafetyMetrics)
