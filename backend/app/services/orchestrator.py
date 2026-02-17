"""Core autonomous coding orchestration service (prototype)."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import get_settings
from app.schemas import (
    ApprovalRequest,
    AuditEntry,
    Artifact,
    ChannelMessageEvent,
    ConnectorTriggerRequest,
    EvaluationMetrics,
    PlanStep,
    ProposedAction,
    RerunFailedStepRequest,
    RunSession,
    RunTaskRequest,
    TimelineEvent,
)
from app.services.evaluation import compute_evaluation_metrics
from app.services.execution import ActionExecutionError, ActionExecutor
from app.services.policy import SafetyPolicy
from app.services.store import RunStore


def _ensure_repo_root_on_path() -> None:
    """Ensure local repo root is importable so `import genxai` works from app folder."""
    repo_root = Path(__file__).resolve().parents[5]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_ensure_repo_root_on_path()

from genxai import AgentFactory, AgentRuntime, CriticReviewFlow, MemorySystem, ToolRegistry  # noqa: E402
from genxai.tools import Tool  # noqa: E402
from genxai.tools.builtin import *  # noqa: F403,F401,E402 - register built-in tools


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GenXBotOrchestrator:
    """Orchestrates planning, approval, and execution timeline for runs."""

    def __init__(self, store: RunStore, policy: SafetyPolicy) -> None:
        self._store = store
        self._policy = policy
        self._settings = get_settings()
        self._executor = ActionExecutor(
            policy=policy,
            retry_attempts=self._settings.action_retry_attempts,
            retry_backoff_seconds=self._settings.action_retry_backoff_seconds,
        )
        self._genxai_runtime_ctx: dict[str, dict[str, Any]] = {}

    def _prepare_workspace(self, run_id: str, repo_path: str) -> str:
        """Create per-run sandbox workspace if enabled, else use repo path directly."""
        source = Path(repo_path).resolve()
        if not self._settings.sandbox_enabled:
            return str(source)

        sandbox_root = Path(self._settings.sandbox_root).resolve()
        sandbox_root.mkdir(parents=True, exist_ok=True)
        sandbox_path = sandbox_root / run_id

        if sandbox_path.exists():
            shutil.rmtree(sandbox_path)

        shutil.copytree(
            source,
            sandbox_path,
            dirs_exist_ok=False,
            ignore=shutil.ignore_patterns(
                ".genxai",
                ".venv",
                "node_modules",
                "__pycache__",
                ".pytest_cache",
            ),
        )
        return str(sandbox_path)

    def _add_audit(
        self,
        run: RunSession,
        *,
        actor: str,
        actor_role: str,
        action: str,
        detail: str,
    ) -> None:
        run.audit_log.append(
            AuditEntry(
                actor=actor,
                actor_role=actor_role,
                action=action,
                detail=detail,
            )
        )

    def _tool_map(self) -> dict[str, Tool]:
        return {tool.metadata.name: tool for tool in ToolRegistry.list_all()}

    def _build_redis_client(self) -> Optional[Any]:
        if not self._settings.redis_enabled:
            return None
        try:
            import redis  # type: ignore

            return redis.from_url(self._settings.redis_url)
        except Exception:
            return None

    def _build_graph_client(self) -> Optional[Any]:
        if not self._settings.graph_enabled:
            return None

        backend = self._settings.graph_backend.lower().strip()
        if backend != "neo4j":
            return None

        try:
            from neo4j import GraphDatabase  # type: ignore

            return GraphDatabase.driver(
                self._settings.neo4j_uri,
                auth=(self._settings.neo4j_user, self._settings.neo4j_password),
            )
        except Exception:
            return None

    def _build_genxai_stack(self, run_id: str, goal: str) -> dict[str, Any]:
        tools = self._tool_map()
        preferred_tools = [
            "directory_scanner",
            "file_reader",
            "file_writer",
            "code_executor",
            "data_validator",
            "regex_matcher",
        ]
        enabled_tools = [name for name in preferred_tools if name in tools]

        planner = AgentFactory.create_agent(
            id=f"planner_{run_id}",
            role="Codebase Planner",
            goal="Produce safe, testable coding plans from user goals",
            llm_model="gpt-4",
            tools=enabled_tools,
            enable_memory=True,
        )
        executor = AgentFactory.create_agent(
            id=f"executor_{run_id}",
            role="Code Executor",
            goal="Propose and execute coding actions safely",
            llm_model="gpt-4",
            tools=enabled_tools,
            enable_memory=True,
        )
        reviewer = AgentFactory.create_agent(
            id=f"reviewer_{run_id}",
            role="Code Reviewer",
            goal="Review plans and actions for safety and quality",
            llm_model="gpt-4",
            tools=enabled_tools,
            enable_memory=True,
        )

        openai_key = os.getenv("OPENAI_API_KEY")
        planner_runtime = AgentRuntime(agent=planner, openai_api_key=openai_key)
        executor_runtime = AgentRuntime(agent=executor, openai_api_key=openai_key)
        reviewer_runtime = AgentRuntime(agent=reviewer, openai_api_key=openai_key)

        planner_runtime.set_tools(tools)
        executor_runtime.set_tools(tools)
        reviewer_runtime.set_tools(tools)

        memory = MemorySystem(
            agent_id=f"genxbot_{run_id}",
            redis_client=self._build_redis_client(),
            graph_db=self._build_graph_client(),
            persistence_enabled=self._settings.memory_persistence_enabled,
            persistence_path=Path(self._settings.memory_persistence_path),
            persistence_backend=self._settings.memory_persistence_backend,
            persistence_sqlite_path=Path(self._settings.memory_sqlite_path),
        )
        planner_runtime.set_memory(memory)
        executor_runtime.set_memory(memory)
        reviewer_runtime.set_memory(memory)

        return {
            "planner": planner,
            "executor": executor,
            "reviewer": reviewer,
            "planner_runtime": planner_runtime,
            "executor_runtime": executor_runtime,
            "reviewer_runtime": reviewer_runtime,
            "memory": memory,
            "tools": tools,
            "goal": goal,
        }

    async def _run_genxai_pipeline(
        self,
        run_id: str,
        goal: str,
        repo_path: str,
        context: str | None,
    ) -> dict[str, Any]:
        stack = self._genxai_runtime_ctx[run_id]
        planner_runtime: AgentRuntime = stack["planner_runtime"]
        executor_runtime: AgentRuntime = stack["executor_runtime"]
        reviewer_runtime: AgentRuntime = stack["reviewer_runtime"]

        planner_task = (
            "Create a concise execution plan for the coding goal. "
            "Return bullet points with repo analysis, code edits, and tests."
        )
        planner_result = await planner_runtime.execute(
            task=planner_task,
            context={"goal": goal, "repo_path": repo_path, "context": context or ""},
        )
        plan_text = planner_result.get("output", "")

        executor_task = (
            "Given the plan, propose two actions in plain text: one command and one edit. "
            "Prefer safe test/lint command first."
        )
        executor_result = await executor_runtime.execute(
            task=executor_task,
            context={
                "goal": goal,
                "repo_path": repo_path,
                "plan": plan_text,
            },
        )

        review_flow = CriticReviewFlow(
            agents=[stack["executor"], stack["reviewer"]],
            max_iterations=1,
        )
        review_state = await review_flow.run(
            input_data={"goal": goal, "repo_path": repo_path},
            state={
                "task": "Review the proposed coding approach for risks and completeness.",
                "critic_task": "Provide concrete risk feedback and improvements.",
                "accept": True,
            },
            max_iterations=5,
        )

        return {
            "plan_text": plan_text,
            "executor_output": executor_result.get("output", ""),
            "review": review_state.get("last_critique", {}),
        }

    def create_run(self, request: RunTaskRequest) -> RunSession:
        run_id = f"run_{os.urandom(5).hex()}"
        workspace_path = self._prepare_workspace(run_id=run_id, repo_path=request.repo_path)

        plan_steps = [
            PlanStep(title="Ingest repository and identify project context"),
            PlanStep(title="Generate implementation plan from goal"),
            PlanStep(title="Propose safe code edits"),
            PlanStep(title="Run lint/tests and summarize result"),
        ]
        base_actions = [
            ProposedAction(
                action_type="command",
                description="Run unit tests to establish baseline",
                command="pytest -q",
            ),
            ProposedAction(
                action_type="edit",
                description="Apply patch for requested feature implementation",
                file_path=f"{workspace_path}/TARGET_FILE.py",
                patch=(
                    "FULL_FILE_CONTENT:\n"
                    "# generated by genxbot\n"
                    "def generated_feature():\n"
                    "    return 'replace with real implementation'\n"
                ),
            ),
        ]

        recipe_actions: list[ProposedAction] = []
        for template in request.recipe_actions:
            file_path = template.file_path
            if template.action_type == "edit":
                if not file_path:
                    file_path = f"{workspace_path}/TARGET_FILE.py"
                elif not Path(file_path).is_absolute():
                    file_path = str(Path(workspace_path) / file_path)

            recipe_actions.append(
                ProposedAction(
                    action_type=template.action_type,
                    description=template.description,
                    command=template.command,
                    file_path=file_path,
                    patch=template.patch,
                )
            )

        run = RunSession(
            id=run_id,
            goal=request.goal,
            repo_path=request.repo_path,
            sandbox_path=workspace_path,
            status="created",
            plan_steps=plan_steps,
            pending_actions=[],
            memory_summary=(
                "Initial memory: user asked for autonomous coding workflow with "
                "repo ingest, plan, edit, and test loop."
            ),
            timeline=[
                TimelineEvent(
                    agent="system",
                    event="genxai_bootstrap",
                    content="Initializing GenXAI agents, runtime, tools, and memory.",
                )
            ],
            artifacts=[],
        )
        run.created_at = _now()
        run.updated_at = run.created_at

        self._genxai_runtime_ctx[run.id] = self._build_genxai_stack(run.id, request.goal)

        openai_key = os.getenv("OPENAI_API_KEY")
        pipeline_output: dict[str, Any] = {}
        if openai_key:
            try:
                pipeline_output = asyncio.run(
                    self._run_genxai_pipeline(
                        run_id=run.id,
                        goal=request.goal,
                        repo_path=workspace_path,
                        context=request.context,
                    )
                )
                run.timeline.append(
                    TimelineEvent(
                        agent="genxai_runtime",
                        event="pipeline_executed",
                        content="Planner/executor/reviewer pipeline completed with live LLM runtime.",
                    )
                )
            except Exception as exc:
                run.timeline.append(
                    TimelineEvent(
                        agent="genxai_runtime",
                        event="pipeline_fallback",
                        content=f"Live pipeline failed, fallback activated: {exc}",
                    )
                )
        else:
            run.timeline.append(
                TimelineEvent(
                    agent="genxai_runtime",
                    event="pipeline_fallback",
                    content="OPENAI_API_KEY missing; using deterministic fallback while keeping GenXAI wiring active.",
                )
            )

        proposed_actions = recipe_actions or base_actions
        if recipe_actions:
            run.timeline.append(
                TimelineEvent(
                    agent="recipe",
                    event="recipe_actions_loaded",
                    content=f"Loaded {len(recipe_actions)} executable actions from recipe definition.",
                )
            )
        if pipeline_output.get("executor_output"):
            first_edit = next((a for a in proposed_actions if a.action_type == "edit"), None)
            if first_edit:
                first_edit.patch = (
                    "FULL_FILE_CONTENT:\n"
                    "# generated by genxbot from GenXAI executor output\n"
                    "GENXAI_EXECUTOR_OUTPUT = '''\n"
                    f"{pipeline_output['executor_output'][:1200]}\n"
                    "'''\n"
                )
                if not first_edit.file_path:
                    first_edit.file_path = f"{workspace_path}/TARGET_FILE.py"

        for action in proposed_actions:
            action.safe = action.action_type == "command" and bool(
                action.command and self._policy.is_safe_command(action.command)
            )

        has_gate = any(self._policy.requires_approval(a) for a in proposed_actions)
        status = "awaiting_approval" if has_gate else "running"
        run.status = status
        run.pending_actions = proposed_actions
        run.timeline.extend(
            [
                TimelineEvent(
                    agent="planner",
                    event="plan_created",
                    content="Generated 4-step autonomous coding plan.",
                ),
                TimelineEvent(
                    agent="executor",
                    event="actions_proposed",
                    content=f"Proposed {len(proposed_actions)} actions; awaiting approval.",
                ),
            ]
        )
        self._add_audit(
            run,
            actor=request.requested_by,
            actor_role="executor",
            action="run_created",
            detail=f"Run created for goal: {request.goal}",
        )
        run.artifacts.append(
            Artifact(
                kind="plan",
                title="Initial execution plan",
                content=pipeline_output.get(
                    "plan_text",
                    "\n".join(f"- {step.title}" for step in plan_steps),
                ),
            )
        )
        if pipeline_output.get("review"):
            run.artifacts.append(
                Artifact(
                    kind="summary",
                    title="Critic review feedback",
                    content=str(pipeline_output["review"]),
                )
            )

        run.memory_summary = (
            "GenXAI memory initialized for this run. "
            "Planner/executor/reviewer context is tracked via MemorySystem."
        )
        run.updated_at = _now()
        return self._store.create(run)

    def create_run_from_connector(self, trigger: ConnectorTriggerRequest) -> RunSession:
        payload = trigger.payload or {}
        connector = trigger.connector

        default_repo = trigger.default_repo_path or "."
        actor = f"{connector}_connector"
        goal = f"Handle {connector} event: {trigger.event_type}"
        context_parts: list[str] = []

        if connector == "github":
            repo = payload.get("repository", {}).get("full_name")
            pr_title = payload.get("pull_request", {}).get("title")
            issue_title = payload.get("issue", {}).get("title")
            goal = (
                f"Analyze GitHub {trigger.event_type} and prepare code/test updates"
                f" for {repo or 'repository'}"
            )
            if pr_title:
                context_parts.append(f"PR title: {pr_title}")
            if issue_title:
                context_parts.append(f"Issue title: {issue_title}")

        elif connector == "jira":
            issue = payload.get("issue", {})
            key = issue.get("key")
            summary = issue.get("fields", {}).get("summary")
            goal = f"Address Jira {trigger.event_type} for {key or 'ticket'}"
            if summary:
                context_parts.append(f"Jira summary: {summary}")

        elif connector == "slack":
            event = payload.get("event", {})
            text = event.get("text") or payload.get("text")
            channel = event.get("channel") or payload.get("channel")
            goal = f"Respond to Slack {trigger.event_type} with coding workflow actions"
            if channel:
                context_parts.append(f"Channel: {channel}")
            if text:
                context_parts.append(f"Message: {text}")

        request = RunTaskRequest(
            goal=goal,
            repo_path=default_repo,
            context="\n".join(context_parts) if context_parts else None,
            requested_by=actor,
        )
        run = self.create_run(request)
        run.timeline.append(
            TimelineEvent(
                agent="connector",
                event="connector_trigger_received",
                content=f"{connector}:{trigger.event_type} accepted and converted to run {run.id}",
            )
        )
        self._add_audit(
            run,
            actor=actor,
            actor_role="executor",
            action="connector_trigger",
            detail=f"Connector event {connector}:{trigger.event_type} created run.",
        )
        run.updated_at = _now()
        return self._store.update(run)

    def create_run_from_channel_event(
        self,
        event: ChannelMessageEvent,
        default_repo_path: str | None = None,
    ) -> RunSession:
        repo_path = default_repo_path or "."
        goal = f"Respond to {event.channel} message with autonomous coding workflow assistance"
        context_parts = [
            f"Channel: {event.channel}",
            f"Event type: {event.event_type}",
            f"User ID: {event.user_id}",
            f"Channel ID: {event.channel_id}",
            f"Message: {event.text}",
        ]
        if event.thread_id:
            context_parts.append(f"Thread ID: {event.thread_id}")
        if event.message_id:
            context_parts.append(f"Message ID: {event.message_id}")

        run = self.create_run(
            RunTaskRequest(
                goal=goal,
                repo_path=repo_path,
                context="\n".join(context_parts),
                requested_by=f"{event.channel}:{event.user_id}",
            )
        )
        run.timeline.append(
            TimelineEvent(
                agent="channel_adapter",
                event="channel_message_received",
                content=(
                    f"{event.channel}:{event.event_type} accepted for user {event.user_id} "
                    f"in channel {event.channel_id}; mapped to run {run.id}"
                ),
            )
        )
        self._add_audit(
            run,
            actor=f"{event.channel}:{event.user_id}",
            actor_role="executor",
            action="channel_event",
            detail=f"Inbound {event.channel} event {event.event_type} created run.",
        )
        run.artifacts.append(
            Artifact(
                kind="summary",
                title=f"Inbound {event.channel} message",
                content=event.text,
            )
        )
        run.updated_at = _now()
        return self._store.update(run)

    def get_run(self, run_id: str) -> RunSession | None:
        return self._store.get(run_id)

    def list_runs(self) -> list[RunSession]:
        return list(self._store.list_runs())

    def get_evaluation_metrics(self) -> EvaluationMetrics:
        return compute_evaluation_metrics(self.list_runs())

    def get_run_audit_log(self, run_id: str) -> list[AuditEntry] | None:
        run = self._store.get(run_id)
        if not run:
            return None
        return list(run.audit_log)

    def rerun_failed_step(self, run_id: str, request: RerunFailedStepRequest) -> RunSession | None:
        run = self._store.get(run_id)
        if not run:
            return None

        if not self._policy.can_approve(request.actor_role):
            run.timeline.append(
                TimelineEvent(
                    agent="system",
                    event="rerun_denied",
                    content=f"Actor role {request.actor_role} is not permitted to request reruns.",
                )
            )
            self._add_audit(
                run,
                actor=request.actor,
                actor_role=request.actor_role,
                action="rerun_denied",
                detail="Insufficient role for rerun request.",
            )
            run.updated_at = _now()
            return self._store.update(run)

        target: ProposedAction | None = None
        if request.action_id:
            target = next(
                (a for a in run.pending_actions if a.id == request.action_id and a.status == "rejected"),
                None,
            )
        else:
            target = next((a for a in reversed(run.pending_actions) if a.status == "rejected"), None)

        if not target:
            run.timeline.append(
                TimelineEvent(
                    agent="system",
                    event="rerun_skipped",
                    content="No rejected action available for re-run.",
                )
            )
            run.updated_at = _now()
            self._add_audit(
                run,
                actor=request.actor,
                actor_role=request.actor_role,
                action="rerun_skipped",
                detail="No rejected action available for re-run.",
            )
            return self._store.update(run)

        replay = target.model_copy(deep=True)
        replay.id = f"action_{os.urandom(4).hex()}"
        replay.status = "pending"

        run.pending_actions.append(replay)
        run.status = "awaiting_approval"

        if request.step_id:
            for step in run.plan_steps:
                if step.id == request.step_id:
                    step.status = "pending"
                    break

        run.timeline.append(
            TimelineEvent(
                agent="user",
                event="rerun_requested",
                content=(
                    f"Requested re-run for action {target.id}; created retry action {replay.id}. "
                    f"Comment: {request.comment or 'n/a'}"
                ),
            )
        )
        self._add_audit(
            run,
            actor=request.actor,
            actor_role=request.actor_role,
            action="rerun_requested",
            detail=f"Retry action {replay.id} created from {target.id}.",
        )
        run.artifacts.append(
            Artifact(
                kind="summary",
                title=f"Re-run requested for {target.id}",
                content="A new pending action was created from the rejected action for retry.",
            )
        )

        run.updated_at = _now()
        return self._store.update(run)

    def decide_action(self, run_id: str, approval: ApprovalRequest) -> RunSession | None:
        run = self._store.get(run_id)
        if not run:
            return None

        if not self._policy.can_approve(approval.actor_role):
            run.timeline.append(
                TimelineEvent(
                    agent="system",
                    event="approval_denied",
                    content=f"Actor role {approval.actor_role} is not permitted to approve actions.",
                )
            )
            self._add_audit(
                run,
                actor=approval.actor,
                actor_role=approval.actor_role,
                action="approval_denied",
                detail=f"Denied approval attempt for action {approval.action_id}.",
            )
            run.updated_at = _now()
            return self._store.update(run)

        chosen = next((a for a in run.pending_actions if a.id == approval.action_id), None)
        if not chosen:
            return run

        chosen.status = "approved" if approval.approve else "rejected"
        run.timeline.append(
            TimelineEvent(
                agent="user",
                event="approval_decision",
                content=(
                    f"Action {chosen.id} {chosen.status}. "
                    f"Comment: {approval.comment or 'n/a'}"
                ),
            )
        )
        self._add_audit(
            run,
            actor=approval.actor,
            actor_role=approval.actor_role,
            action="approval_decision",
            detail=f"Action {chosen.id} marked {chosen.status}.",
        )

        if approval.approve:
            try:
                artifact_kind, artifact_content = self._executor.execute(
                    chosen,
                    workspace_root=run.sandbox_path or run.repo_path,
                )
                chosen.status = "executed"
                run.timeline.append(
                    TimelineEvent(
                        agent="executor",
                        event="action_executed",
                        content=f"Executed {chosen.action_type}: {chosen.description}",
                    )
                )
                run.artifacts.append(
                    Artifact(
                        kind=artifact_kind,
                        title=f"Result for {chosen.id}",
                        content=artifact_content,
                    )
                )
            except ActionExecutionError as exc:
                chosen.status = "rejected"
                run.timeline.append(
                    TimelineEvent(
                        agent="executor",
                        event="action_blocked",
                        content=f"Blocked execution for {chosen.id}: {exc}",
                    )
                )
                run.artifacts.append(
                    Artifact(
                        kind="summary",
                        title=f"Blocked action {chosen.id}",
                        content=str(exc),
                    )
                )

        all_done = all(action.status in {"executed", "rejected"} for action in run.pending_actions)
        if all_done:
            run.status = "completed"
            run.timeline.append(
                TimelineEvent(
                    agent="reviewer",
                    event="run_completed",
                    content="Run completed with all actions resolved.",
                )
            )
            run.artifacts.append(
                Artifact(
                    kind="summary",
                    title="Run summary",
                    content="Prototype execution complete. Integrate real tool runners next.",
                )
            )
        else:
            run.status = "awaiting_approval"

        run.updated_at = _now()
        return self._store.update(run)
