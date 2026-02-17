"""API routes for autonomous coding runs."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import get_settings
from app.schemas import (
    ApprovalRequest,
    ApproverAllowlistResponse,
    ApproverAllowlistUpdateRequest,
    ChannelInboundRequest,
    ChannelInboundResponse,
    ChannelMaintenanceMode,
    ChannelMaintenanceModeUpdateRequest,
    ChannelMetricsSnapshot,
    ChannelSessionSnapshot,
    ChannelTrustPolicy,
    OutboundRetryQueueSnapshot,
    OutboundRetryJob,
    QueueHealthSnapshot,
    IdempotencyCacheSnapshot,
    AdminAuditSnapshot,
    ChannelTrustPolicyUpdateRequest,
    AuditEntry,
    AdminAuditEntry,
    ConnectorTriggerRequest,
    ConnectorTriggerResponse,
    EvaluationMetrics,
    PairingApprovalRequest,
    PairingApprovalResponse,
    PendingPairingCode,
    QueueJobStatusResponse,
    RerunFailedStepRequest,
    RecipeCreateRequest,
    RecipeActionTemplate,
    RecipeDefinition,
    RecipeListResponse,
    RunSession,
    RunTaskRequest,
)
from app.services.channels import parse_channel_event
from app.services.channels import parse_channel_command
from app.services.channel_outbound import (
    ChannelOutboundService,
    format_outbound_action_decision,
    format_outbound_run_created,
    format_outbound_status,
)
from app.services.channel_observability import ChannelObservabilityService
from app.services.channel_sessions import ChannelSessionService
from app.services.channel_trust import ChannelTrustService
from app.services.orchestrator import GenXBotOrchestrator
from app.services.policy import SafetyPolicy
from app.services.queue import RunQueueService
from app.services.rate_limit import InMemoryRateLimiter, build_rate_limiter_dependency
from app.services.authz import AdminAuditService, AdminAuthorizationService
from app.services.store import RunStore
from app.services.webhook_security import WebhookSecurityService
from app.services.outbound_retry_queue import OutboundRetryQueueService

_settings = get_settings()
_store = (
    RunStore(db_path=_settings.run_store_path)
    if _settings.run_store_backend.lower() == "sqlite"
    else RunStore()
)
_policy = SafetyPolicy()
_orchestrator = GenXBotOrchestrator(store=_store, policy=_policy)
_run_queue = RunQueueService(
    orchestrator=_orchestrator,
    worker_enabled=_settings.queue_worker_enabled,
)
_rate_limiter = InMemoryRateLimiter(
    requests_per_window=_settings.rate_limit_requests,
    window_seconds=_settings.rate_limit_window_seconds,
)
_rate_limit_dependency = build_rate_limiter_dependency(
    limiter=_rate_limiter,
    enabled=_settings.rate_limit_enabled,
)

_channel_state_db = (
    _settings.channel_state_sqlite_path
    if _settings.channel_state_backend.strip().lower() == "sqlite"
    else None
)

_channel_trust = ChannelTrustService(db_path=_channel_state_db)
_channel_sessions = ChannelSessionService(db_path=_channel_state_db)
_channel_outbound = ChannelOutboundService(
    enabled=_settings.channel_outbound_enabled,
    slack_webhook_url=_settings.slack_outbound_webhook_url,
    telegram_bot_token=_settings.telegram_bot_token,
    telegram_api_base_url=_settings.telegram_api_base_url,
)
_channel_observability = ChannelObservabilityService()
_outbound_retry_queue = OutboundRetryQueueService(
    send_fn=lambda channel, channel_id, text, thread_id: _channel_outbound.send(
        channel=channel,
        channel_id=channel_id,
        text=text,
        thread_id=thread_id,
    ),
    worker_enabled=_settings.channel_outbound_retry_worker_enabled,
    max_attempts=_settings.channel_outbound_retry_max_attempts,
    backoff_seconds=_settings.channel_outbound_retry_backoff_seconds,
)
_webhook_security = WebhookSecurityService(
    enabled=_settings.channel_webhook_security_enabled,
    slack_secret=_settings.slack_signing_secret,
    telegram_secret=_settings.telegram_webhook_secret,
    slack_secrets=[s.strip() for s in _settings.slack_signing_secrets.split(",") if s.strip()],
    telegram_secrets=[s.strip() for s in _settings.telegram_webhook_secrets.split(",") if s.strip()],
    replay_window_seconds=_settings.webhook_replay_window_seconds,
)
_command_approver_allowlist = {
    v.strip() for v in _settings.channel_command_approver_allowlist.split(",") if v.strip()
}
_channel_maintenance: dict[str, ChannelMaintenanceMode] = {
    "slack": ChannelMaintenanceMode(channel="slack", enabled=False, reason=""),
    "telegram": ChannelMaintenanceMode(channel="telegram", enabled=False, reason=""),
}
_channel_idempotency_cache: dict[str, tuple[float, ChannelInboundResponse]] = {}
_channel_idempotency_cache_ttl_seconds = max(_settings.channel_idempotency_cache_ttl_seconds, 1)
_channel_idempotency_cache_max_entries = max(_settings.channel_idempotency_cache_max_entries, 1)
_admin_authz = AdminAuthorizationService()
_admin_audit = AdminAuditService(max_entries=_settings.admin_audit_max_entries)

_RECIPES_LIBRARY_DIR = Path(__file__).resolve().parents[1] / "recipes"


def _fallback_recipe() -> RecipeDefinition:
    return RecipeDefinition(
        id="test-hardening",
        name="Test Hardening",
        description="Improve and stabilize tests around a target area",
        goal_template="Harden tests for {target_area} and summarize gaps",
        context_template="focus={target_area}\npriority={priority}",
        tags=["testing", "quality"],
        enabled=True,
    )


def _load_default_recipes_from_files() -> dict[str, RecipeDefinition]:
    recipes: dict[str, RecipeDefinition] = {}
    if not _RECIPES_LIBRARY_DIR.exists() or not _RECIPES_LIBRARY_DIR.is_dir():
        fallback = _fallback_recipe()
        return {fallback.id: fallback}

    for recipe_dir in sorted(_RECIPES_LIBRARY_DIR.iterdir(), key=lambda p: p.name):
        if not recipe_dir.is_dir():
            continue
        definition_file = recipe_dir / "recipe.json"
        if not definition_file.exists():
            continue
        try:
            payload = json.loads(definition_file.read_text(encoding="utf-8"))
            recipe = RecipeDefinition(**payload)
        except Exception:
            continue
        recipes[recipe.id] = recipe

    if not recipes:
        fallback = _fallback_recipe()
        recipes[fallback.id] = fallback

    return recipes


_recipes: dict[str, RecipeDefinition] = _load_default_recipes_from_files()


def _render_template(template: str | None, values: dict[str, str]) -> str | None:
    if template is None:
        return None
    if not values:
        return template
    try:
        return template.format(**values)
    except Exception:
        return template


def _render_recipe_actions(
    action_templates: list[RecipeActionTemplate],
    values: dict[str, str],
) -> list[RecipeActionTemplate]:
    rendered: list[RecipeActionTemplate] = []
    for action in action_templates:
        rendered.append(
            RecipeActionTemplate(
                action_type=action.action_type,
                description=_render_template(action.description, values) or action.description,
                command=_render_template(action.command, values),
                file_path=_render_template(action.file_path, values),
                patch=_render_template(action.patch, values),
            )
        )
    return rendered


def _resolve_recipe_request(request: RunTaskRequest) -> RunTaskRequest:
    if not request.recipe_id:
        return request
    recipe = _recipes.get(request.recipe_id)
    if not recipe or not recipe.enabled:
        raise HTTPException(status_code=404, detail=f"Recipe not found: {request.recipe_id}")

    render_values = {
        **request.recipe_inputs,
        "recipe_id": recipe.id,
        "recipe_name": recipe.name,
    }
    rendered_goal = _render_template(recipe.goal_template, render_values) or request.goal
    rendered_context = _render_template(recipe.context_template, render_values)
    rendered_actions = _render_recipe_actions(recipe.action_templates, render_values)
    merged_context = "\n".join(v for v in [request.context, rendered_context] if v)

    return request.model_copy(
        update={
            "goal": rendered_goal,
            "context": merged_context or None,
            "recipe_actions": rendered_actions,
        }
    )


def _send_outbound(
    *,
    channel: str,
    channel_id: str,
    text: str,
    thread_id: str | None,
) -> str:
    delivery = _channel_outbound.send(
        channel=channel,
        channel_id=channel_id,
        text=text,
        thread_id=thread_id,
    )
    if delivery.startswith("failed:"):
        job = _outbound_retry_queue.enqueue(
            channel=channel,
            channel_id=channel_id,
            text=text,
            thread_id=thread_id,
        )
        delivery = f"{delivery};queued_retry:{job.id}"

    _channel_observability.record_outbound(channel=channel, delivery_status=delivery)
    return delivery


def _prune_channel_idempotency_cache(now: float | None = None) -> None:
    current = now or time.time()
    expires_before = current - _channel_idempotency_cache_ttl_seconds

    expired = [k for k, (ts, _) in _channel_idempotency_cache.items() if ts < expires_before]
    for key in expired:
        _channel_idempotency_cache.pop(key, None)

    overflow = len(_channel_idempotency_cache) - _channel_idempotency_cache_max_entries
    if overflow > 0:
        oldest = sorted(_channel_idempotency_cache.items(), key=lambda item: item[1][0])
        for key, _ in oldest[:overflow]:
            _channel_idempotency_cache.pop(key, None)


def _get_cached_channel_response(token: str | None) -> ChannelInboundResponse | None:
    if not token:
        return None

    _prune_channel_idempotency_cache()
    entry = _channel_idempotency_cache.get(token)
    if not entry:
        return None
    return entry[1]


def _cache_channel_response(token: str | None, response: ChannelInboundResponse) -> ChannelInboundResponse:
    if token:
        _prune_channel_idempotency_cache()
        _channel_idempotency_cache[token] = (time.time(), response)
    return response


def _idempotency_cache_snapshot() -> IdempotencyCacheSnapshot:
    _prune_channel_idempotency_cache()
    return IdempotencyCacheSnapshot(
        entries=len(_channel_idempotency_cache),
        ttl_seconds=_channel_idempotency_cache_ttl_seconds,
        max_entries=_channel_idempotency_cache_max_entries,
    )


def _admin_origin(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _admin_audit_snapshot() -> AdminAuditSnapshot:
    return AdminAuditSnapshot(
        entries=len(_admin_audit.list_entries()),
        max_entries=_admin_audit.max_entries,
    )


def _get_maintenance(channel: str) -> ChannelMaintenanceMode:
    key = channel.strip().lower()
    if key not in _channel_maintenance:
        raise HTTPException(status_code=400, detail=f"Unsupported channel: {channel}")
    return _channel_maintenance[key]

router = APIRouter(
    prefix="/runs",
    tags=["runs"],
    dependencies=[Depends(_rate_limit_dependency)],
)


def get_orchestrator() -> GenXBotOrchestrator:
    return _orchestrator


@router.post("", response_model=RunSession)
def create_run(
    request: RunTaskRequest,
    orchestrator: GenXBotOrchestrator = Depends(get_orchestrator),
) -> RunSession:
    return orchestrator.create_run(_resolve_recipe_request(request))


@router.get("/recipes", response_model=RecipeListResponse)
def list_recipes() -> RecipeListResponse:
    return RecipeListResponse(recipes=sorted(_recipes.values(), key=lambda r: r.id))


@router.get("/recipes/{recipe_id}", response_model=RecipeDefinition)
def get_recipe(recipe_id: str) -> RecipeDefinition:
    recipe = _recipes.get(recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@router.post("/recipes", response_model=RecipeDefinition)
def create_recipe(request: RecipeCreateRequest, raw_request: Request) -> RecipeDefinition:
    _admin_authz.require(raw_request, minimum_role="admin")
    recipe = RecipeDefinition(
        id=request.id.strip(),
        name=request.name.strip(),
        description=request.description.strip(),
        goal_template=request.goal_template,
        context_template=request.context_template,
        tags=[t.strip() for t in request.tags if t.strip()],
        action_templates=request.action_templates,
        enabled=True,
    )
    _recipes[recipe.id] = recipe
    return recipe


@router.get("", response_model=list[RunSession])
def list_runs(orchestrator: GenXBotOrchestrator = Depends(get_orchestrator)) -> list[RunSession]:
    return orchestrator.list_runs()


@router.get("/metrics", response_model=EvaluationMetrics)
def get_metrics(
    orchestrator: GenXBotOrchestrator = Depends(get_orchestrator),
) -> EvaluationMetrics:
    return orchestrator.get_evaluation_metrics()


@router.get("/{run_id}", response_model=RunSession)
def get_run(
    run_id: str,
    orchestrator: GenXBotOrchestrator = Depends(get_orchestrator),
) -> RunSession:
    run = orchestrator.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/{run_id}/approval", response_model=RunSession)
def decide_approval(
    run_id: str,
    request: ApprovalRequest,
    orchestrator: GenXBotOrchestrator = Depends(get_orchestrator),
) -> RunSession:
    run = orchestrator.decide_action(run_id, request)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/{run_id}/rerun-failed-step", response_model=RunSession)
def rerun_failed_step(
    run_id: str,
    request: RerunFailedStepRequest,
    orchestrator: GenXBotOrchestrator = Depends(get_orchestrator),
) -> RunSession:
    run = orchestrator.rerun_failed_step(run_id, request)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/audit", response_model=list[AuditEntry])
def get_run_audit(
    run_id: str,
    orchestrator: GenXBotOrchestrator = Depends(get_orchestrator),
) -> list[AuditEntry]:
    audit = orchestrator.get_run_audit_log(run_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return audit


@router.post("/triggers/{connector}", response_model=ConnectorTriggerResponse)
def trigger_connector_run(
    connector: str,
    request: ConnectorTriggerRequest,
    orchestrator: GenXBotOrchestrator = Depends(get_orchestrator),
) -> ConnectorTriggerResponse:
    if connector != request.connector:
        raise HTTPException(
            status_code=400,
            detail="Path connector and payload connector mismatch",
        )
    run = orchestrator.create_run_from_connector(request)
    return ConnectorTriggerResponse(
        connector=request.connector,
        event_type=request.event_type,
        run=run,
    )


@router.post("/channels/{channel}", response_model=ChannelInboundResponse)
def ingest_channel_event(
    channel: str,
    request: ChannelInboundRequest,
    raw_request: Request,
    orchestrator: GenXBotOrchestrator = Depends(get_orchestrator),
) -> ChannelInboundResponse:
    trace_id = _channel_observability.new_trace_id()
    idempotency_key = raw_request.headers.get("x-idempotency-key", "").strip()
    idempotency_token = (
        f"{request.channel}:{idempotency_key}" if idempotency_key else None
    )
    cached = _get_cached_channel_response(idempotency_token)
    if cached:
        return cached

    if channel != request.channel:
        raise HTTPException(
            status_code=400,
            detail="Path channel and payload channel mismatch",
        )

    maintenance = _get_maintenance(request.channel)
    if maintenance.enabled:
        return _cache_channel_response(idempotency_token, ChannelInboundResponse(
            channel=request.channel,
            event_type=request.event_type,
            command="maintenance",
            outbound_text=(
                f"⚠️ {request.channel} maintenance mode enabled. "
                f"{maintenance.reason or 'Please try again later.'}"
            ),
            outbound_delivery="skipped:maintenance",
            trace_id=trace_id,
        ))

    try:
        normalized = parse_channel_event(
            channel=request.channel,
            event_type=request.event_type,
            payload=request.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        _webhook_security.verify(channel=request.channel, headers=dict(raw_request.headers))
    except ValueError as exc:
        if "Replay detected" in str(exc):
            _channel_observability.record_replay_blocked()
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if not _channel_trust.is_trusted(request.channel, normalized.user_id):
        pending = _channel_trust.issue_pairing_code(request.channel, normalized.user_id)
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Sender is not paired/allowlisted for this channel",
                "pairing_code": pending.code,
                "channel": pending.channel,
                "user_id": pending.user_id,
            },
        )

    session_key = _channel_sessions.build_session_key(
        channel=normalized.channel,
        channel_id=normalized.channel_id,
        thread_id=normalized.thread_id,
        user_id=normalized.user_id,
    )
    command, args = parse_channel_command(normalized.text)
    _channel_observability.record_inbound(
        channel=normalized.channel,
        command=command or "run",
    )

    if command == "status":
        run_id = args.split()[0] if args else _channel_sessions.get_latest_run(session_key)
        if not run_id:
            outbound_text = "No run context found for this conversation. Start with /run <goal>."
            delivery = _send_outbound(
                channel=normalized.channel,
                channel_id=normalized.channel_id,
                thread_id=normalized.thread_id,
                text=outbound_text,
            )
            return _cache_channel_response(idempotency_token, ChannelInboundResponse(
                channel=request.channel,
                event_type=request.event_type,
                command=command,
                outbound_text=outbound_text,
                outbound_delivery=delivery,
                session_key=session_key,
                trace_id=trace_id,
            ))
        run = orchestrator.get_run(run_id)
        if not run:
            outbound_text = f"Run {run_id} not found."
            delivery = _send_outbound(
                channel=normalized.channel,
                channel_id=normalized.channel_id,
                thread_id=normalized.thread_id,
                text=outbound_text,
            )
            return _cache_channel_response(idempotency_token, ChannelInboundResponse(
                channel=request.channel,
                event_type=request.event_type,
                command=command,
                outbound_text=outbound_text,
                outbound_delivery=delivery,
                session_key=session_key,
                trace_id=trace_id,
            ))
        outbound_text = format_outbound_status(run)
        delivery = _send_outbound(
            channel=normalized.channel,
            channel_id=normalized.channel_id,
            thread_id=normalized.thread_id,
            text=outbound_text,
        )
        return _cache_channel_response(idempotency_token, ChannelInboundResponse(
            channel=request.channel,
            event_type=request.event_type,
            run=run,
            command=command,
            outbound_text=outbound_text,
            outbound_delivery=delivery,
            session_key=session_key,
            trace_id=trace_id,
        ))

    if command in {"approve", "reject"}:
        if _command_approver_allowlist and normalized.user_id not in _command_approver_allowlist:
            outbound_text = (
                f"User {normalized.user_id} is not allowed to execute /{command}. "
                "Ask an approved operator to review this action."
            )
            delivery = _send_outbound(
                channel=normalized.channel,
                channel_id=normalized.channel_id,
                thread_id=normalized.thread_id,
                text=outbound_text,
            )
            return _cache_channel_response(idempotency_token, ChannelInboundResponse(
                channel=request.channel,
                event_type=request.event_type,
                command=command,
                outbound_text=outbound_text,
                outbound_delivery=delivery,
                session_key=session_key,
                trace_id=trace_id,
            ))

        parts = args.split()
        if not parts:
            outbound_text = "Usage: /approve <action_id> [run_id] or /reject <action_id> [run_id]"
            delivery = _send_outbound(
                channel=normalized.channel,
                channel_id=normalized.channel_id,
                thread_id=normalized.thread_id,
                text=outbound_text,
            )
            return _cache_channel_response(idempotency_token, ChannelInboundResponse(
                channel=request.channel,
                event_type=request.event_type,
                command=command,
                outbound_text=outbound_text,
                outbound_delivery=delivery,
                session_key=session_key,
                trace_id=trace_id,
            ))
        action_id = parts[0]
        run_id = parts[1] if len(parts) > 1 else _channel_sessions.get_latest_run(session_key)
        if not run_id:
            outbound_text = "No run context found. Provide run_id or start with /run <goal>."
            delivery = _send_outbound(
                channel=normalized.channel,
                channel_id=normalized.channel_id,
                thread_id=normalized.thread_id,
                text=outbound_text,
            )
            return _cache_channel_response(idempotency_token, ChannelInboundResponse(
                channel=request.channel,
                event_type=request.event_type,
                command=command,
                outbound_text=outbound_text,
                outbound_delivery=delivery,
                session_key=session_key,
                trace_id=trace_id,
            ))

        run = orchestrator.decide_action(
            run_id,
            ApprovalRequest(
                action_id=action_id,
                approve=command == "approve",
                actor=f"{normalized.channel}:{normalized.user_id}",
                actor_role="approver",
            ),
        )
        if not run:
            outbound_text = f"Run {run_id} not found."
            delivery = _send_outbound(
                channel=normalized.channel,
                channel_id=normalized.channel_id,
                thread_id=normalized.thread_id,
                text=outbound_text,
            )
            return _cache_channel_response(idempotency_token, ChannelInboundResponse(
                channel=request.channel,
                event_type=request.event_type,
                command=command,
                outbound_text=outbound_text,
                outbound_delivery=delivery,
                session_key=session_key,
                trace_id=trace_id,
            ))

        outbound_text = format_outbound_action_decision(run, approved=command == "approve")
        delivery = _send_outbound(
            channel=normalized.channel,
            channel_id=normalized.channel_id,
            thread_id=normalized.thread_id,
            text=outbound_text,
        )
        return _cache_channel_response(idempotency_token, ChannelInboundResponse(
            channel=request.channel,
            event_type=request.event_type,
            run=run,
            command=command,
            outbound_text=outbound_text,
            outbound_delivery=delivery,
            session_key=session_key,
            trace_id=trace_id,
        ))

    run_goal = args if command == "run" and args else normalized.text
    run = orchestrator.create_run_from_channel_event(
        normalized.model_copy(update={"text": run_goal}),
        default_repo_path=request.default_repo_path,
    )
    _channel_sessions.attach_run(session_key, run.id)
    outbound_text = format_outbound_run_created(run)
    delivery = _send_outbound(
        channel=normalized.channel,
        channel_id=normalized.channel_id,
        thread_id=normalized.thread_id,
        text=outbound_text,
    )
    return _cache_channel_response(idempotency_token, ChannelInboundResponse(
        channel=request.channel,
        event_type=request.event_type,
        run=run,
        command=command or "run",
        outbound_text=outbound_text,
        outbound_delivery=delivery,
        session_key=session_key,
        trace_id=trace_id,
    ))


@router.get("/channels/sessions", response_model=list[ChannelSessionSnapshot])
def list_channel_sessions() -> list[ChannelSessionSnapshot]:
    return _channel_sessions.list_snapshots()


@router.get("/channels/metrics", response_model=ChannelMetricsSnapshot)
def get_channel_metrics() -> ChannelMetricsSnapshot:
    return _channel_observability.snapshot()


@router.get("/channels/{channel}/maintenance", response_model=ChannelMaintenanceMode)
def get_channel_maintenance(channel: str, raw_request: Request) -> ChannelMaintenanceMode:
    _admin_authz.require(raw_request, minimum_role="approver")
    return _get_maintenance(channel)


@router.put("/channels/{channel}/maintenance", response_model=ChannelMaintenanceMode)
def update_channel_maintenance(
    channel: str,
    request: ChannelMaintenanceModeUpdateRequest,
    raw_request: Request,
) -> ChannelMaintenanceMode:
    context = _admin_authz.require(raw_request, minimum_role="admin")
    current = _get_maintenance(channel)
    before = current.model_dump()
    updated = ChannelMaintenanceMode(
        channel=current.channel,
        enabled=request.enabled,
        reason=request.reason.strip(),
    )
    _channel_maintenance[current.channel] = updated
    _admin_audit.record(
        context=context,
        action="channel_maintenance_update",
        origin=_admin_origin(raw_request),
        trace_id=_channel_observability.new_trace_id(),
        before=before,
        after=updated.model_dump(),
    )
    return updated


@router.get("/channels/outbound-retry", response_model=OutboundRetryQueueSnapshot)
def get_outbound_retry_queue() -> OutboundRetryQueueSnapshot:
    return _outbound_retry_queue.snapshot()


@router.get("/channels/outbound-retry/deadletters", response_model=list[OutboundRetryJob])
def list_outbound_retry_deadletters() -> list[OutboundRetryJob]:
    return _outbound_retry_queue.list_dead_letters()


@router.post("/channels/outbound-retry/replay/{job_id}", response_model=OutboundRetryQueueSnapshot)
def replay_outbound_deadletter(job_id: str, raw_request: Request) -> OutboundRetryQueueSnapshot:
    context = _admin_authz.require(raw_request, minimum_role="approver")
    before = _outbound_retry_queue.snapshot().model_dump()
    replayed = _outbound_retry_queue.replay_dead_letter(job_id)
    if not replayed:
        raise HTTPException(status_code=404, detail="Dead-letter job not found")
    after_snapshot = _outbound_retry_queue.snapshot()
    _admin_audit.record(
        context=context,
        action="deadletter_replay",
        origin=_admin_origin(raw_request),
        trace_id=_channel_observability.new_trace_id(),
        before=before,
        after=after_snapshot.model_dump(),
    )
    return after_snapshot


@router.get("/channels/approver-allowlist", response_model=ApproverAllowlistResponse)
def get_channel_approver_allowlist(raw_request: Request) -> ApproverAllowlistResponse:
    _admin_authz.require(raw_request, minimum_role="approver")
    return ApproverAllowlistResponse(users=sorted(_command_approver_allowlist))


@router.put("/channels/approver-allowlist", response_model=ApproverAllowlistResponse)
def update_channel_approver_allowlist(
    request: ApproverAllowlistUpdateRequest,
    raw_request: Request,
) -> ApproverAllowlistResponse:
    context = _admin_authz.require(raw_request, minimum_role="admin")
    global _command_approver_allowlist
    before = {"users": sorted(_command_approver_allowlist)}
    _command_approver_allowlist = {str(v).strip() for v in request.users if str(v).strip()}
    response = ApproverAllowlistResponse(users=sorted(_command_approver_allowlist))
    _admin_audit.record(
        context=context,
        action="approver_allowlist_update",
        origin=_admin_origin(raw_request),
        trace_id=_channel_observability.new_trace_id(),
        before=before,
        after=response.model_dump(),
    )
    return response


@router.get("/channels/{channel}/trust-policy", response_model=ChannelTrustPolicy)
def get_channel_trust_policy(channel: str) -> ChannelTrustPolicy:
    try:
        return _channel_trust.get_policy(channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/channels/{channel}/trust-policy", response_model=ChannelTrustPolicy)
def update_channel_trust_policy(
    channel: str,
    request: ChannelTrustPolicyUpdateRequest,
    raw_request: Request,
) -> ChannelTrustPolicy:
    context = _admin_authz.require(raw_request, minimum_role="admin")
    before = _channel_trust.get_policy(channel).model_dump()
    try:
        updated = _channel_trust.set_policy(
            channel=channel,
            dm_policy=request.dm_policy,
            allow_from=request.allow_from,
        )
        _admin_audit.record(
            context=context,
            action="trust_policy_update",
            origin=_admin_origin(raw_request),
            trace_id=_channel_observability.new_trace_id(),
            before=before,
            after=updated.model_dump(),
        )
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/channels/{channel}/pairing/pending", response_model=list[PendingPairingCode])
def list_pending_pairing_codes(channel: str) -> list[PendingPairingCode]:
    try:
        return _channel_trust.list_pending_codes(channel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/channels/{channel}/pairing/approve", response_model=PairingApprovalResponse)
def approve_pairing_code(
    channel: str,
    request: PairingApprovalRequest,
    raw_request: Request,
) -> PairingApprovalResponse:
    context = _admin_authz.require(raw_request, minimum_role="approver")
    before = {"pending": [p.model_dump() for p in _channel_trust.list_pending_codes(channel)]}
    try:
        user_id = _channel_trust.approve_pairing_code(channel, request.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = PairingApprovalResponse(
        channel=channel.strip().lower(),
        code=request.code.strip().upper(),
        approved=user_id is not None,
        user_id=user_id,
    )
    _admin_audit.record(
        context=context,
        action="pairing_approve",
        origin=_admin_origin(raw_request),
        trace_id=_channel_observability.new_trace_id(),
        before=before,
        after=response.model_dump(),
    )
    return response


@router.get("/channels/admin-audit", response_model=list[AdminAuditEntry])
def list_admin_audit(raw_request: Request) -> list[AdminAuditEntry]:
    _admin_authz.require(raw_request, minimum_role="approver")
    return _admin_audit.list_entries()


@router.get("/channels/admin-audit/stats", response_model=AdminAuditSnapshot)
def get_admin_audit_stats(raw_request: Request) -> AdminAuditSnapshot:
    _admin_authz.require(raw_request, minimum_role="approver")
    return _admin_audit_snapshot()


@router.post("/channels/admin-audit/clear", response_model=AdminAuditSnapshot)
def clear_admin_audit(raw_request: Request) -> AdminAuditSnapshot:
    _admin_authz.require(raw_request, minimum_role="admin")
    _admin_audit.clear()
    return _admin_audit_snapshot()


@router.get("/channels/idempotency-cache", response_model=IdempotencyCacheSnapshot)
def get_idempotency_cache_stats(raw_request: Request) -> IdempotencyCacheSnapshot:
    _admin_authz.require(raw_request, minimum_role="approver")
    return _idempotency_cache_snapshot()


@router.post("/channels/idempotency-cache/clear", response_model=IdempotencyCacheSnapshot)
def clear_idempotency_cache(raw_request: Request) -> IdempotencyCacheSnapshot:
    context = _admin_authz.require(raw_request, minimum_role="admin")
    before = _idempotency_cache_snapshot().model_dump()
    _channel_idempotency_cache.clear()
    after = _idempotency_cache_snapshot()
    _admin_audit.record(
        context=context,
        action="idempotency_cache_clear",
        origin=_admin_origin(raw_request),
        trace_id=_channel_observability.new_trace_id(),
        before=before,
        after=after.model_dump(),
    )
    return after


@router.post("/queue", response_model=QueueJobStatusResponse)
def enqueue_run_job(
    request: RunTaskRequest,
) -> QueueJobStatusResponse:
    return _run_queue.enqueue_run(request)


@router.get("/queue/health", response_model=QueueHealthSnapshot)
def get_queue_health() -> QueueHealthSnapshot:
    return QueueHealthSnapshot(
        run_queue_pending=_run_queue.pending_count(),
        run_worker_alive=_run_queue.is_worker_alive(),
        outbound_retry_pending=_outbound_retry_queue.pending_count(),
        outbound_retry_dead_lettered=_outbound_retry_queue.dead_letter_count(),
        outbound_retry_worker_alive=_outbound_retry_queue.is_worker_alive(),
    )


@router.get("/queue/{job_id}", response_model=QueueJobStatusResponse)
def get_run_job_status(job_id: str) -> QueueJobStatusResponse:
    job = _run_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
