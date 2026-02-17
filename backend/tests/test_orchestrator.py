from pathlib import Path
import hashlib
import hmac
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import ApprovalRequest, RerunFailedStepRequest, RunTaskRequest
from app.services.orchestrator import GenXBotOrchestrator
import app.api.routes_runs as runs_routes
from app.services.policy import SafetyPolicy
from app.services.queue import RunQueueService
from app.services.store import RunStore


def build_orchestrator() -> GenXBotOrchestrator:
    return GenXBotOrchestrator(store=RunStore(), policy=SafetyPolicy())


def approver_request(action_id: str, approve: bool, comment: str = "") -> ApprovalRequest:
    return ApprovalRequest(
        action_id=action_id,
        approve=approve,
        comment=comment,
        actor="tester",
        actor_role="approver",
    )


def test_create_run_generates_plan_and_pending_actions(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="Add API tests and fix lint", repo_path=str(tmp_path))
    )

    assert run.id.startswith("run_")
    assert run.status == "awaiting_approval"
    assert len(run.plan_steps) == 4
    assert len(run.pending_actions) >= 1
    assert len(run.timeline) >= 2


def test_approval_executes_action_and_updates_artifacts(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="Implement feature", repo_path=str(tmp_path))
    )

    action = next(a for a in run.pending_actions if a.action_type == "edit")
    assert run.sandbox_path is not None
    action.file_path = str(Path(run.sandbox_path) / "approval_executes.py")
    action.patch = "FULL_FILE_CONTENT:\nprint('ok')\n"
    updated = orchestrator.decide_action(
        run.id,
        approver_request(action.id, True, "Proceed"),
    )

    assert updated is not None
    assert any(a.status == "executed" for a in updated.pending_actions)
    assert len(updated.artifacts) >= 2
    assert any(evt.event == "action_executed" for evt in updated.timeline)


def test_approval_executes_real_edit_within_workspace(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="Implement feature", repo_path=str(tmp_path))
    )

    edit_action = next(a for a in run.pending_actions if a.action_type == "edit")
    assert run.sandbox_path is not None
    edit_action.file_path = str(Path(run.sandbox_path) / "genxbot_output.py")
    edit_action.patch = "FULL_FILE_CONTENT:\nprint('hello from genxbot')\n"

    updated = orchestrator.decide_action(
        run.id,
        approver_request(edit_action.id, True, "Proceed edit"),
    )

    assert updated is not None
    assert any(a.status == "executed" for a in updated.pending_actions if a.id == edit_action.id)
    created_file = Path(run.sandbox_path) / "genxbot_output.py"
    assert created_file.exists()
    content = created_file.read_text(encoding="utf-8")
    assert "hello from genxbot" in content


def test_approval_applies_unified_diff_patch(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    target = tmp_path / "sample.py"
    target.write_text("print('old')\n", encoding="utf-8")

    run = orchestrator.create_run(
        RunTaskRequest(goal="Patch file", repo_path=str(tmp_path))
    )
    assert run.sandbox_path is not None
    sandbox_target = Path(run.sandbox_path) / "sample.py"

    edit_action = next(a for a in run.pending_actions if a.action_type == "edit")
    edit_action.file_path = str(sandbox_target)
    edit_action.patch = (
        "--- a/sample.py\n"
        "+++ b/sample.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-print('old')\n"
        "+print('new')\n"
    )

    updated = orchestrator.decide_action(
        run.id,
        approver_request(edit_action.id, True, "apply diff"),
    )

    assert updated is not None
    assert sandbox_target.read_text(encoding="utf-8") == "print('new')\n"
    assert any(a.status == "executed" for a in updated.pending_actions if a.id == edit_action.id)


def test_command_with_shell_operator_is_blocked(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="Unsafe command test", repo_path=str(tmp_path))
    )

    cmd_action = next(a for a in run.pending_actions if a.action_type == "command")
    cmd_action.command = "pytest -q && echo hacked"

    updated = orchestrator.decide_action(
        run.id,
        approver_request(cmd_action.id, True, "try unsafe"),
    )

    assert updated is not None
    chosen = next(a for a in updated.pending_actions if a.id == cmd_action.id)
    assert chosen.status == "rejected"
    assert any(evt.event == "action_blocked" for evt in updated.timeline)


def test_run_executes_edits_inside_sandbox_not_source(tmp_path: Path) -> None:
    source_repo = tmp_path / "source_repo"
    source_repo.mkdir(parents=True, exist_ok=True)
    source_file = source_repo / "module.py"
    source_file.write_text("print('source')\n", encoding="utf-8")

    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="Sandbox edit", repo_path=str(source_repo))
    )

    assert run.sandbox_path is not None
    assert Path(run.sandbox_path) != source_repo
    sandbox_file = Path(run.sandbox_path) / "module.py"
    assert sandbox_file.exists()

    edit_action = next(a for a in run.pending_actions if a.action_type == "edit")
    edit_action.file_path = str(sandbox_file)
    edit_action.patch = "FULL_FILE_CONTENT:\nprint('sandbox')\n"

    updated = orchestrator.decide_action(
        run.id,
        approver_request(edit_action.id, True, "apply sandbox edit"),
    )

    assert updated is not None
    assert source_file.read_text(encoding="utf-8") == "print('source')\n"
    assert sandbox_file.read_text(encoding="utf-8") == "print('sandbox')"


def test_evaluation_metrics_aggregate_from_runs(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    run1 = orchestrator.create_run(
        RunTaskRequest(goal="Eval run one", repo_path=str(tmp_path))
    )
    action1 = run1.pending_actions[0]
    updated1 = orchestrator.decide_action(
        run1.id,
        approver_request(action1.id, True, "ok"),
    )
    assert updated1 is not None

    run2 = orchestrator.create_run(
        RunTaskRequest(goal="Eval run two", repo_path=str(tmp_path))
    )
    for action in run2.pending_actions:
        orchestrator.decide_action(
            run2.id,
            approver_request(action.id, False, "reject"),
        )

    metrics = orchestrator.get_evaluation_metrics()
    assert metrics.total_runs >= 2
    assert metrics.latency.samples >= 2
    assert metrics.safety.total_actions >= 4
    assert metrics.safety.rejected_actions >= 2


def test_metrics_endpoint_returns_evaluation_payload(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="API metrics", repo_path=str(tmp_path))
    )
    for action in run.pending_actions:
        orchestrator.decide_action(
            run.id,
            approver_request(action.id, False, "reject for metric"),
        )

    original_orchestrator = runs_routes._orchestrator
    runs_routes._orchestrator = orchestrator
    try:
        client = TestClient(create_app())
        response = client.get("/api/v1/runs/metrics")
        assert response.status_code == 200
        payload = response.json()
        assert "total_runs" in payload
        assert "latency" in payload
        assert "safety" in payload
        assert payload["safety"]["rejected_actions"] >= 2
    finally:
        runs_routes._orchestrator = original_orchestrator


def test_rerun_failed_step_creates_new_pending_action(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="Rerun failed action", repo_path=str(tmp_path))
    )

    rejected = next(a for a in run.pending_actions if a.action_type == "edit")
    updated = orchestrator.decide_action(
        run.id,
        approver_request(rejected.id, False, "reject once"),
    )
    assert updated is not None
    assert any(a.id == rejected.id and a.status == "rejected" for a in updated.pending_actions)

    rerun = orchestrator.rerun_failed_step(
        run.id,
        RerunFailedStepRequest(
            action_id=rejected.id,
            comment="retry after fixes",
            actor="tester",
            actor_role="approver",
        ),
    )
    assert rerun is not None
    assert rerun.status == "awaiting_approval"

    retries = [a for a in rerun.pending_actions if a.description == rejected.description and a.id != rejected.id]
    assert retries
    assert retries[-1].status == "pending"
    assert any(evt.event == "rerun_requested" for evt in rerun.timeline)


def test_rerun_failed_step_endpoint(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="Rerun failed step endpoint", repo_path=str(tmp_path))
    )

    rejected = next(a for a in run.pending_actions if a.action_type == "edit")
    orchestrator.decide_action(
        run.id,
        approver_request(rejected.id, False, "reject once"),
    )

    original_orchestrator = runs_routes._orchestrator
    runs_routes._orchestrator = orchestrator
    try:
        client = TestClient(create_app())
        response = client.post(
            f"/api/v1/runs/{run.id}/rerun-failed-step",
            json={
                "action_id": rejected.id,
                "comment": "retry now",
                "actor": "tester",
                "actor_role": "approver",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "awaiting_approval"
        assert len(payload["pending_actions"]) >= 3
        assert any(evt["event"] == "rerun_requested" for evt in payload["timeline"])
    finally:
        runs_routes._orchestrator = original_orchestrator


def test_viewer_cannot_approve_action(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="RBAC approval denied", repo_path=str(tmp_path))
    )
    action = run.pending_actions[0]

    updated = orchestrator.decide_action(
        run.id,
        ApprovalRequest(
            action_id=action.id,
            approve=True,
            comment="try as viewer",
            actor="alice",
            actor_role="viewer",
        ),
    )

    assert updated is not None
    same = next(a for a in updated.pending_actions if a.id == action.id)
    assert same.status == "pending"
    assert any(evt.event == "approval_denied" for evt in updated.timeline)
    assert any(entry.action == "approval_denied" for entry in updated.audit_log)


def test_audit_endpoint_returns_entries(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()
    run = orchestrator.create_run(
        RunTaskRequest(goal="Audit endpoint", repo_path=str(tmp_path), requested_by="owner")
    )
    action = run.pending_actions[0]
    orchestrator.decide_action(run.id, approver_request(action.id, False, "audit reject"))

    original_orchestrator = runs_routes._orchestrator
    runs_routes._orchestrator = orchestrator
    try:
        client = TestClient(create_app())
        response = client.get(f"/api/v1/runs/{run.id}/audit")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) >= 2
        assert any(entry["action"] == "run_created" for entry in payload)
    finally:
        runs_routes._orchestrator = original_orchestrator


def test_github_trigger_creates_run(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    runs_routes._orchestrator = orchestrator
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/runs/triggers/github",
            json={
                "connector": "github",
                "event_type": "pull_request.opened",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "repository": {"full_name": "genexsus-ai/genxai"},
                    "pull_request": {"title": "Fix failing tests"},
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["connector"] == "github"
        assert payload["run"]["id"].startswith("run_")
        assert any(evt["event"] == "connector_trigger_received" for evt in payload["run"]["timeline"])
    finally:
        runs_routes._orchestrator = original_orchestrator


def test_trigger_connector_mismatch_returns_400(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    runs_routes._orchestrator = orchestrator
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/runs/triggers/github",
            json={
                "connector": "jira",
                "event_type": "issue.updated",
                "default_repo_path": str(tmp_path),
                "payload": {"issue": {"key": "PROJ-101"}},
            },
        )
        assert response.status_code == 400
    finally:
        runs_routes._orchestrator = original_orchestrator


def test_queue_endpoint_enqueues_and_completes_job(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_queue = runs_routes._run_queue
    runs_routes._orchestrator = orchestrator
    runs_routes._run_queue = RunQueueService(orchestrator=orchestrator, worker_enabled=True)
    try:
        client = TestClient(create_app())
        enqueue = client.post(
            "/api/v1/runs/queue",
            json={
                "goal": "Queued run",
                "repo_path": str(tmp_path),
                "requested_by": "queue-test",
            },
        )
        assert enqueue.status_code == 200
        job_id = enqueue.json()["job_id"]

        status_payload = None
        for _ in range(20):
            status = client.get(f"/api/v1/runs/queue/{job_id}")
            assert status.status_code == 200
            status_payload = status.json()
            if status_payload["status"] == "completed":
                break
            time.sleep(0.05)

        assert status_payload is not None
        assert status_payload["status"] in {"running", "completed"}
        if status_payload["status"] == "completed":
            assert status_payload["run"]["id"].startswith("run_")
    finally:
        runs_routes._run_queue.stop()
        runs_routes._run_queue = original_queue
        runs_routes._orchestrator = original_orchestrator


def test_rate_limit_returns_429_when_exceeded() -> None:
    original_requests = runs_routes._rate_limiter._requests
    original_window = runs_routes._rate_limiter._window
    original_hits = dict(runs_routes._rate_limiter._hits)
    runs_routes._rate_limiter._requests = 1
    runs_routes._rate_limiter._window = 60
    runs_routes._rate_limiter._hits.clear()
    try:
        client = TestClient(create_app())
        first = client.get("/api/v1/runs")
        assert first.status_code == 200
        second = client.get("/api/v1/runs")
        assert second.status_code == 429
    finally:
        runs_routes._rate_limiter._requests = original_requests
        runs_routes._rate_limiter._window = original_window
        runs_routes._rate_limiter._hits.clear()
        runs_routes._rate_limiter._hits.update(original_hits)


def test_slack_channel_ingest_creates_run(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    runs_routes._orchestrator = orchestrator
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U123",
                        "channel": "C789",
                        "text": "please fix failing tests",
                        "ts": "1710000000.000100",
                    }
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["channel"] == "slack"
        assert payload["run"]["id"].startswith("run_")
        assert any(
            evt["event"] == "channel_message_received" for evt in payload["run"]["timeline"]
        )
    finally:
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_telegram_channel_ingest_creates_run(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    runs_routes._orchestrator = orchestrator
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("telegram", dm_policy="open", allow_from=[])
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/runs/channels/telegram",
            json={
                "channel": "telegram",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "message": {
                        "message_id": 42,
                        "from": {"id": 1001},
                        "chat": {"id": -222},
                        "text": "generate implementation plan",
                    }
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["channel"] == "telegram"
        assert payload["run"]["id"].startswith("run_")
        assert any(
            evt["event"] == "channel_message_received" for evt in payload["run"]["timeline"]
        )
    finally:
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_channel_mismatch_returns_400(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    runs_routes._orchestrator = orchestrator
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "telegram",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {"message": {"from": {"id": 1}, "chat": {"id": 2}, "text": "hi"}},
            },
        )
        assert response.status_code == 400
    finally:
        runs_routes._orchestrator = original_orchestrator


def test_unpaired_channel_sender_returns_403_with_pairing_code(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    runs_routes._orchestrator = orchestrator
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-UNPAIRED",
                        "channel": "C1",
                        "text": "hello from unknown sender",
                    }
                },
            },
        )
        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["message"].startswith("Sender is not paired")
        assert detail["channel"] == "slack"
        assert detail["user_id"] == "U-UNPAIRED"
        assert len(detail["pairing_code"]) >= 4
    finally:
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_pairing_approval_allows_subsequent_channel_ingest(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    runs_routes._orchestrator = orchestrator
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    try:
        client = TestClient(create_app())

        blocked = client.post(
            "/api/v1/runs/channels/telegram",
            json={
                "channel": "telegram",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "message": {
                        "from": {"id": 5001},
                        "chat": {"id": -99},
                        "text": "need help",
                    }
                },
            },
        )
        assert blocked.status_code == 403
        pairing_code = blocked.json()["detail"]["pairing_code"]

        pending = client.get("/api/v1/runs/channels/telegram/pairing/pending")
        assert pending.status_code == 200
        assert any(item["code"] == pairing_code for item in pending.json())

        approved = client.post(
            "/api/v1/runs/channels/telegram/pairing/approve",
            json={"code": pairing_code, "actor": "admin-user"},
        )
        assert approved.status_code == 200
        assert approved.json()["approved"] is True
        assert approved.json()["user_id"] == "5001"

        accepted = client.post(
            "/api/v1/runs/channels/telegram",
            json={
                "channel": "telegram",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "message": {
                        "from": {"id": 5001},
                        "chat": {"id": -99},
                        "text": "need help after pairing",
                    }
                },
            },
        )
        assert accepted.status_code == 200
        assert accepted.json()["run"]["id"].startswith("run_")
    finally:
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_open_dm_policy_allows_unpaired_sender(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    runs_routes._orchestrator = orchestrator
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    try:
        client = TestClient(create_app())

        updated = client.put(
            "/api/v1/runs/channels/slack/trust-policy",
            json={"dm_policy": "open", "allow_from": []},
        )
        assert updated.status_code == 200
        assert updated.json()["dm_policy"] == "open"

        response = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-OPEN",
                        "channel": "C-open",
                        "text": "hello while open",
                    }
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["run"]["id"].startswith("run_")
    finally:
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_channel_run_command_creates_run_and_session(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_sessions = runs_routes._channel_sessions
    runs_routes._orchestrator = orchestrator
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._channel_sessions = ChannelSessionService()
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-CMD",
                        "channel": "C-CMD",
                        "text": "/run fix flaky tests",
                        "ts": "1710000000.000200",
                    }
                },
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["command"] == "run"
        assert payload["outbound_text"].startswith("✅ Run created")
        assert payload["session_key"].startswith("slack:C-CMD")
        assert payload["run"]["id"].startswith("run_")
    finally:
        runs_routes._channel_sessions = original_sessions
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_channel_status_command_uses_session_context(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_sessions = runs_routes._channel_sessions
    runs_routes._orchestrator = orchestrator
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("telegram", dm_policy="open", allow_from=[])
    runs_routes._channel_sessions = ChannelSessionService()
    try:
        client = TestClient(create_app())
        created = client.post(
            "/api/v1/runs/channels/telegram",
            json={
                "channel": "telegram",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "message": {
                        "from": {"id": 7007},
                        "chat": {"id": -55},
                        "text": "/run improve docs",
                    }
                },
            },
        )
        assert created.status_code == 200

        status = client.post(
            "/api/v1/runs/channels/telegram",
            json={
                "channel": "telegram",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "message": {
                        "from": {"id": 7007},
                        "chat": {"id": -55},
                        "text": "/status",
                    }
                },
            },
        )
        assert status.status_code == 200
        body = status.json()
        assert body["command"] == "status"
        assert body["run"]["id"] == created.json()["run"]["id"]
        assert body["outbound_text"].startswith("📌 Run")
    finally:
        runs_routes._channel_sessions = original_sessions
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_channel_approve_command_changes_action_status(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_sessions = runs_routes._channel_sessions
    runs_routes._orchestrator = orchestrator
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._channel_sessions = ChannelSessionService()
    try:
        client = TestClient(create_app())
        created = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-APP",
                        "channel": "C-APP",
                        "text": "/run build tests",
                    }
                },
            },
        )
        assert created.status_code == 200
        run = created.json()["run"]
        pending = next(a for a in run["pending_actions"] if a["status"] == "pending")

        approve = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-APP",
                        "channel": "C-APP",
                        "text": f"/approve {pending['id']}",
                    }
                },
            },
        )
        assert approve.status_code == 200
        assert approve.json()["command"] == "approve"
        assert "Action approved" in approve.json()["outbound_text"]
    finally:
        runs_routes._channel_sessions = original_sessions
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_webhook_security_rejects_invalid_signature_when_enabled(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_security = runs_routes._webhook_security
    runs_routes._orchestrator = orchestrator
    from app.services.channel_trust import ChannelTrustService
    from app.services.webhook_security import WebhookSecurityService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._webhook_security = WebhookSecurityService(
        enabled=True,
        slack_secret="slack-secret",
        telegram_secret="telegram-secret",
        replay_window_seconds=300,
    )
    try:
        client = TestClient(create_app())
        ts = str(int(time.time()))
        event_id = "evt-invalid"
        response = client.post(
            "/api/v1/runs/channels/slack",
            headers={
                "x-genx-timestamp": ts,
                "x-genx-event-id": event_id,
                "x-genx-signature": "bad-signature",
            },
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-SIG",
                        "channel": "C-SIG",
                        "text": "/run signed request",
                    }
                },
            },
        )
        assert response.status_code == 401
    finally:
        runs_routes._webhook_security = original_security
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_webhook_security_detects_replay_when_enabled(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_security = runs_routes._webhook_security
    runs_routes._orchestrator = orchestrator
    from app.services.channel_trust import ChannelTrustService
    from app.services.webhook_security import WebhookSecurityService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._webhook_security = WebhookSecurityService(
        enabled=True,
        slack_secret="slack-secret",
        telegram_secret="telegram-secret",
        replay_window_seconds=300,
    )
    try:
        client = TestClient(create_app())
        ts = str(int(time.time()))
        event_id = "evt-replay"
        base = f"{ts}:{event_id}".encode("utf-8")
        signature = hmac.new(b"slack-secret", base, hashlib.sha256).hexdigest()

        first = client.post(
            "/api/v1/runs/channels/slack",
            headers={
                "x-genx-timestamp": ts,
                "x-genx-event-id": event_id,
                "x-genx-signature": signature,
            },
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-SIG2",
                        "channel": "C-SIG2",
                        "text": "/run first request",
                    }
                },
            },
        )
        assert first.status_code == 200

        replay = client.post(
            "/api/v1/runs/channels/slack",
            headers={
                "x-genx-timestamp": ts,
                "x-genx-event-id": event_id,
                "x-genx-signature": signature,
            },
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-SIG2",
                        "channel": "C-SIG2",
                        "text": "/status",
                    }
                },
            },
        )
        assert replay.status_code == 401
    finally:
        runs_routes._webhook_security = original_security
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_channel_sessions_endpoint_returns_snapshots(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_sessions = runs_routes._channel_sessions
    runs_routes._orchestrator = orchestrator
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._channel_sessions = ChannelSessionService()
    try:
        client = TestClient(create_app())
        created = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-SESS",
                        "channel": "C-SESS",
                        "text": "/run verify sessions endpoint",
                    }
                },
            },
        )
        assert created.status_code == 200

        sessions = client.get("/api/v1/runs/channels/sessions")
        assert sessions.status_code == 200
        payload = sessions.json()
        assert payload
        assert payload[0]["session_key"].startswith("slack:C-SESS")
        assert payload[0]["latest_run_id"].startswith("run_")
    finally:
        runs_routes._channel_sessions = original_sessions
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_command_approver_allowlist_blocks_unlisted_user(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_sessions = runs_routes._channel_sessions
    original_allowlist = set(runs_routes._command_approver_allowlist)
    runs_routes._orchestrator = orchestrator
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._channel_sessions = ChannelSessionService()
    runs_routes._command_approver_allowlist = {"U-ALLOWED"}
    try:
        client = TestClient(create_app())
        created = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-DENIED",
                        "channel": "C-ALLOW",
                        "text": "/run allowlist test",
                    }
                },
            },
        )
        assert created.status_code == 200
        pending = next(a for a in created.json()["run"]["pending_actions"] if a["status"] == "pending")

        blocked = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-DENIED",
                        "channel": "C-ALLOW",
                        "text": f"/approve {pending['id']}",
                    }
                },
            },
        )
        assert blocked.status_code == 200
        assert "not allowed" in blocked.json()["outbound_text"]
    finally:
        runs_routes._command_approver_allowlist = original_allowlist
        runs_routes._channel_sessions = original_sessions
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_channel_state_services_persist_with_sqlite(tmp_path: Path) -> None:
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService

    db_path = str(tmp_path / "channel_state.sqlite3")

    trust_a = ChannelTrustService(db_path=db_path)
    trust_a.set_policy("slack", dm_policy="open", allow_from=["U-PERSIST"])
    pending = trust_a.issue_pairing_code("telegram", "9001")
    approved_user = trust_a.approve_pairing_code("telegram", pending.code)
    assert approved_user == "9001"

    sessions_a = ChannelSessionService(db_path=db_path)
    skey = sessions_a.build_session_key(
        channel="slack",
        channel_id="C1",
        thread_id=None,
        user_id="U-PERSIST",
    )
    sessions_a.attach_run(skey, "run_persisted")

    trust_b = ChannelTrustService(db_path=db_path)
    policy = trust_b.get_policy("slack")
    assert policy.dm_policy == "open"
    assert "U-PERSIST" in policy.allow_from

    sessions_b = ChannelSessionService(db_path=db_path)
    assert sessions_b.get_latest_run(skey) == "run_persisted"


def test_channel_e2e_chat_workflow_run_status_approve(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_sessions = runs_routes._channel_sessions
    runs_routes._orchestrator = orchestrator
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._channel_sessions = ChannelSessionService()
    try:
        client = TestClient(create_app())

        created = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-E2E",
                        "channel": "C-E2E",
                        "text": "/run implement endpoint tests",
                    }
                },
            },
        )
        assert created.status_code == 200
        run = created.json()["run"]
        assert created.json()["trace_id"].startswith("trace_")

        status = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-E2E",
                        "channel": "C-E2E",
                        "text": "/status",
                    }
                },
            },
        )
        assert status.status_code == 200
        assert status.json()["run"]["id"] == run["id"]

        pending = next(a for a in run["pending_actions"] if a["status"] == "pending")
        approved = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-E2E",
                        "channel": "C-E2E",
                        "text": f"/approve {pending['id']}",
                    }
                },
            },
        )
        assert approved.status_code == 200
        assert approved.json()["command"] == "approve"
        assert approved.json()["trace_id"].startswith("trace_")
    finally:
        runs_routes._channel_sessions = original_sessions
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_channel_admin_allowlist_get_and_update() -> None:
    original_allowlist = set(runs_routes._command_approver_allowlist)
    runs_routes._command_approver_allowlist = {"U-ONE"}
    try:
        client = TestClient(create_app())
        get_before = client.get("/api/v1/runs/channels/approver-allowlist")
        assert get_before.status_code == 200
        assert get_before.json()["users"] == ["U-ONE"]

        update = client.put(
            "/api/v1/runs/channels/approver-allowlist",
            json={"users": ["U-ADMIN", "U-OPS"]},
        )
        assert update.status_code == 200
        assert update.json()["users"] == ["U-ADMIN", "U-OPS"]
    finally:
        runs_routes._command_approver_allowlist = original_allowlist


def test_admin_token_and_role_enforced_for_sensitive_endpoints() -> None:
    original_token = runs_routes._admin_authz._admin_token
    original_allowlist = set(runs_routes._command_approver_allowlist)
    original_admin_audit_entries = list(runs_routes._admin_audit.list_entries())
    runs_routes._admin_authz._admin_token = "token-6b"
    runs_routes._command_approver_allowlist = {"U-ONE"}
    try:
        client = TestClient(create_app())

        unauthorized = client.get("/api/v1/runs/channels/approver-allowlist")
        assert unauthorized.status_code == 401

        insufficient_role = client.put(
            "/api/v1/runs/channels/approver-allowlist",
            headers={
                "x-admin-token": "token-6b",
                "x-admin-actor": "ops-user",
                "x-admin-role": "approver",
            },
            json={"users": ["U-ADMIN"]},
        )
        assert insufficient_role.status_code == 403

        updated = client.put(
            "/api/v1/runs/channels/approver-allowlist",
            headers={
                "x-admin-token": "token-6b",
                "x-admin-actor": "root-admin",
                "x-admin-role": "admin",
            },
            json={"users": ["U-ADMIN", "U-OPS"]},
        )
        assert updated.status_code == 200
        assert updated.json()["users"] == ["U-ADMIN", "U-OPS"]

        admin_audit = client.get(
            "/api/v1/runs/channels/admin-audit",
            headers={
                "x-admin-token": "token-6b",
                "x-admin-actor": "ops-reader",
                "x-admin-role": "approver",
            },
        )
        assert admin_audit.status_code == 200
        entries = admin_audit.json()
        assert entries
        latest = entries[-1]
        assert latest["action"] == "approver_allowlist_update"
        assert latest["actor"] == "root-admin"
        assert latest["origin"]
        assert latest["trace_id"].startswith("trace_")
        assert latest["before"]["users"] == ["U-ONE"]
        assert latest["after"]["users"] == ["U-ADMIN", "U-OPS"]
    finally:
        runs_routes._admin_authz._admin_token = original_token
        runs_routes._command_approver_allowlist = original_allowlist
        runs_routes._admin_audit._entries = original_admin_audit_entries


def test_idempotency_cache_stats_and_admin_clear() -> None:
    original_token = runs_routes._admin_authz._admin_token
    original_cache = dict(runs_routes._channel_idempotency_cache)
    original_ttl = runs_routes._channel_idempotency_cache_ttl_seconds
    original_max = runs_routes._channel_idempotency_cache_max_entries
    original_admin_audit_entries = list(runs_routes._admin_audit.list_entries())

    runs_routes._admin_authz._admin_token = "token-6c"
    runs_routes._channel_idempotency_cache_ttl_seconds = 600
    runs_routes._channel_idempotency_cache_max_entries = 10
    runs_routes._channel_idempotency_cache.clear()
    runs_routes._channel_idempotency_cache["slack:k1"] = (
        time.time(),
        runs_routes.ChannelInboundResponse(channel="slack", event_type="message", command="run"),
    )
    runs_routes._channel_idempotency_cache["telegram:k2"] = (
        time.time(),
        runs_routes.ChannelInboundResponse(channel="telegram", event_type="message", command="status"),
    )
    try:
        client = TestClient(create_app())

        stats = client.get(
            "/api/v1/runs/channels/idempotency-cache",
            headers={
                "x-admin-token": "token-6c",
                "x-admin-actor": "ops-reader",
                "x-admin-role": "approver",
            },
        )
        assert stats.status_code == 200
        assert stats.json()["entries"] == 2
        assert stats.json()["ttl_seconds"] == 600
        assert stats.json()["max_entries"] == 10

        denied_clear = client.post(
            "/api/v1/runs/channels/idempotency-cache/clear",
            headers={
                "x-admin-token": "token-6c",
                "x-admin-actor": "ops-reader",
                "x-admin-role": "approver",
            },
        )
        assert denied_clear.status_code == 403

        cleared = client.post(
            "/api/v1/runs/channels/idempotency-cache/clear",
            headers={
                "x-admin-token": "token-6c",
                "x-admin-actor": "root-admin",
                "x-admin-role": "admin",
            },
        )
        assert cleared.status_code == 200
        assert cleared.json()["entries"] == 0

        admin_audit = client.get(
            "/api/v1/runs/channels/admin-audit",
            headers={
                "x-admin-token": "token-6c",
                "x-admin-actor": "ops-reader",
                "x-admin-role": "approver",
            },
        )
        assert admin_audit.status_code == 200
        latest = admin_audit.json()[-1]
        assert latest["action"] == "idempotency_cache_clear"
        assert latest["before"]["entries"] == 2
        assert latest["after"]["entries"] == 0
    finally:
        runs_routes._admin_authz._admin_token = original_token
        runs_routes._channel_idempotency_cache.clear()
        runs_routes._channel_idempotency_cache.update(original_cache)
        runs_routes._channel_idempotency_cache_ttl_seconds = original_ttl
        runs_routes._channel_idempotency_cache_max_entries = original_max
        runs_routes._admin_audit._entries = original_admin_audit_entries


def test_admin_audit_retention_stats_and_clear() -> None:
    from app.schemas import AdminActorContext

    original_token = runs_routes._admin_authz._admin_token
    original_entries = list(runs_routes._admin_audit.list_entries())
    original_max_entries = runs_routes._admin_audit.max_entries

    runs_routes._admin_authz._admin_token = "token-6d"
    runs_routes._admin_audit._entries = []
    runs_routes._admin_audit._max_entries = 2
    runs_routes._admin_audit.record(
        context=AdminActorContext(actor="a1", actor_role="admin"),
        action="oldest",
        origin="test",
        trace_id="trace_oldest",
        before={},
        after={},
    )
    runs_routes._admin_audit.record(
        context=AdminActorContext(actor="a2", actor_role="admin"),
        action="middle",
        origin="test",
        trace_id="trace_middle",
        before={},
        after={},
    )
    runs_routes._admin_audit.record(
        context=AdminActorContext(actor="a3", actor_role="admin"),
        action="latest",
        origin="test",
        trace_id="trace_latest",
        before={},
        after={},
    )
    try:
        client = TestClient(create_app())

        stats = client.get(
            "/api/v1/runs/channels/admin-audit/stats",
            headers={
                "x-admin-token": "token-6d",
                "x-admin-actor": "ops-reader",
                "x-admin-role": "approver",
            },
        )
        assert stats.status_code == 200
        assert stats.json()["entries"] == 2
        assert stats.json()["max_entries"] == 2

        audit_entries = client.get(
            "/api/v1/runs/channels/admin-audit",
            headers={
                "x-admin-token": "token-6d",
                "x-admin-actor": "ops-reader",
                "x-admin-role": "approver",
            },
        )
        assert audit_entries.status_code == 200
        actions = [e["action"] for e in audit_entries.json()]
        assert actions == ["middle", "latest"]

        denied_clear = client.post(
            "/api/v1/runs/channels/admin-audit/clear",
            headers={
                "x-admin-token": "token-6d",
                "x-admin-actor": "ops-reader",
                "x-admin-role": "approver",
            },
        )
        assert denied_clear.status_code == 403

        cleared = client.post(
            "/api/v1/runs/channels/admin-audit/clear",
            headers={
                "x-admin-token": "token-6d",
                "x-admin-actor": "root-admin",
                "x-admin-role": "admin",
            },
        )
        assert cleared.status_code == 200
        assert cleared.json()["entries"] == 0
    finally:
        runs_routes._admin_authz._admin_token = original_token
        runs_routes._admin_audit._max_entries = original_max_entries
        runs_routes._admin_audit._entries = original_entries


def test_channel_maintenance_mode_blocks_ingest_and_can_be_toggled() -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_sessions = runs_routes._channel_sessions
    original_token = runs_routes._admin_authz._admin_token
    original_maintenance = {
        k: v.model_copy(deep=True) for k, v in runs_routes._channel_maintenance.items()
    }
    original_admin_audit_entries = list(runs_routes._admin_audit.list_entries())

    runs_routes._orchestrator = orchestrator
    runs_routes._admin_authz._admin_token = "token-6e"
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._channel_sessions = ChannelSessionService()
    runs_routes._channel_maintenance["slack"] = runs_routes.ChannelMaintenanceMode(
        channel="slack", enabled=False, reason=""
    )
    try:
        client = TestClient(create_app())

        denied_toggle = client.put(
            "/api/v1/runs/channels/slack/maintenance",
            headers={
                "x-admin-token": "token-6e",
                "x-admin-actor": "ops-approver",
                "x-admin-role": "approver",
            },
            json={"enabled": True, "reason": "maintenance window"},
        )
        assert denied_toggle.status_code == 403

        enabled = client.put(
            "/api/v1/runs/channels/slack/maintenance",
            headers={
                "x-admin-token": "token-6e",
                "x-admin-actor": "root-admin",
                "x-admin-role": "admin",
            },
            json={"enabled": True, "reason": "maintenance window"},
        )
        assert enabled.status_code == 200
        assert enabled.json()["enabled"] is True

        blocked = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-MAINT",
                        "channel": "C-MAINT",
                        "text": "/run should be blocked",
                    }
                },
            },
        )
        assert blocked.status_code == 200
        assert blocked.json()["command"] == "maintenance"
        assert blocked.json()["outbound_delivery"] == "skipped:maintenance"

        disabled = client.put(
            "/api/v1/runs/channels/slack/maintenance",
            headers={
                "x-admin-token": "token-6e",
                "x-admin-actor": "root-admin",
                "x-admin-role": "admin",
            },
            json={"enabled": False, "reason": ""},
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        accepted = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": ".",
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-MAINT",
                        "channel": "C-MAINT",
                        "text": "/run accepted after maintenance",
                    }
                },
            },
        )
        assert accepted.status_code == 200
        assert accepted.json()["run"]["id"].startswith("run_")

        audit = client.get(
            "/api/v1/runs/channels/admin-audit",
            headers={
                "x-admin-token": "token-6e",
                "x-admin-actor": "ops-reader",
                "x-admin-role": "approver",
            },
        )
        assert audit.status_code == 200
        actions = [entry["action"] for entry in audit.json()]
        assert "channel_maintenance_update" in actions
    finally:
        runs_routes._admin_authz._admin_token = original_token
        runs_routes._channel_maintenance.clear()
        runs_routes._channel_maintenance.update(original_maintenance)
        runs_routes._admin_audit._entries = original_admin_audit_entries
        runs_routes._channel_sessions = original_sessions
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_failed_outbound_enqueue_retry_and_exposed_snapshot(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    class _FailingOutbound:
        def send(self, *, channel: str, channel_id: str, text: str, thread_id=None) -> str:
            return "failed:simulated"

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_sessions = runs_routes._channel_sessions
    original_outbound = runs_routes._channel_outbound
    original_retry = runs_routes._outbound_retry_queue
    runs_routes._orchestrator = orchestrator
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService
    from app.services.outbound_retry_queue import OutboundRetryQueueService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._channel_sessions = ChannelSessionService()
    runs_routes._channel_outbound = _FailingOutbound()
    runs_routes._outbound_retry_queue = OutboundRetryQueueService(
        send_fn=lambda channel, channel_id, text, thread_id: "failed:simulated",
        worker_enabled=False,
        max_attempts=3,
        backoff_seconds=0.01,
    )
    try:
        client = TestClient(create_app())
        created = client.post(
            "/api/v1/runs/channels/slack",
            json={
                "channel": "slack",
                "event_type": "message",
                "default_repo_path": str(tmp_path),
                "payload": {
                    "event": {
                        "type": "message",
                        "user": "U-RETRY",
                        "channel": "C-RETRY",
                        "text": "/run test retry queue",
                    }
                },
            },
        )
        assert created.status_code == 200
        assert "queued_retry:" in created.json()["outbound_delivery"]

        snapshot = client.get("/api/v1/runs/channels/outbound-retry")
        assert snapshot.status_code == 200
        assert snapshot.json()["queued"] >= 1

        deadletters_before = client.get("/api/v1/runs/channels/outbound-retry/deadletters")
        assert deadletters_before.status_code == 200
        assert deadletters_before.json() == []

        queue_health = client.get("/api/v1/runs/queue/health")
        assert queue_health.status_code == 200
        assert "run_queue_pending" in queue_health.json()
        assert "outbound_retry_pending" in queue_health.json()
    finally:
        original_retry.stop()
        runs_routes._outbound_retry_queue = original_retry
        runs_routes._channel_outbound = original_outbound
        runs_routes._channel_sessions = original_sessions
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_channel_idempotency_key_returns_cached_response(tmp_path: Path) -> None:
    orchestrator = build_orchestrator()

    original_orchestrator = runs_routes._orchestrator
    original_channel_trust = runs_routes._channel_trust
    original_sessions = runs_routes._channel_sessions
    original_cache = dict(runs_routes._channel_idempotency_cache)
    runs_routes._orchestrator = orchestrator
    from app.services.channel_sessions import ChannelSessionService
    from app.services.channel_trust import ChannelTrustService

    runs_routes._channel_trust = ChannelTrustService()
    runs_routes._channel_trust.set_policy("slack", dm_policy="open", allow_from=[])
    runs_routes._channel_sessions = ChannelSessionService()
    runs_routes._channel_idempotency_cache.clear()
    try:
        client = TestClient(create_app())
        headers = {"x-idempotency-key": "idem-123"}
        payload = {
            "channel": "slack",
            "event_type": "message",
            "default_repo_path": str(tmp_path),
            "payload": {
                "event": {
                    "type": "message",
                    "user": "U-IDEM",
                    "channel": "C-IDEM",
                    "text": "/run idempotent run",
                }
            },
        }

        first = client.post("/api/v1/runs/channels/slack", headers=headers, json=payload)
        second = client.post("/api/v1/runs/channels/slack", headers=headers, json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["run"]["id"] == second.json()["run"]["id"]

        runs = client.get("/api/v1/runs")
        assert runs.status_code == 200
        assert len(runs.json()) == 1
    finally:
        runs_routes._channel_idempotency_cache.clear()
        runs_routes._channel_idempotency_cache.update(original_cache)
        runs_routes._channel_sessions = original_sessions
        runs_routes._channel_trust = original_channel_trust
        runs_routes._orchestrator = original_orchestrator


def test_deadletter_replay_endpoint_requeues_job() -> None:
    from app.services.outbound_retry_queue import OutboundRetryQueueService

    def _always_fail(channel, channel_id, text, thread_id):
        return "failed:forced"

    queue = OutboundRetryQueueService(
        send_fn=_always_fail,
        worker_enabled=False,
        max_attempts=1,
        backoff_seconds=0.0,
    )
    job = queue.enqueue(channel="slack", channel_id="C1", text="hello", thread_id=None)
    queue.process_one()

    original_queue = runs_routes._outbound_retry_queue
    runs_routes._outbound_retry_queue = queue
    try:
        client = TestClient(create_app())
        deadletters = client.get("/api/v1/runs/channels/outbound-retry/deadletters")
        assert deadletters.status_code == 200
        assert any(j["id"] == job.id for j in deadletters.json())

        replay = client.post(f"/api/v1/runs/channels/outbound-retry/replay/{job.id}")
        assert replay.status_code == 200
        assert replay.json()["queued"] >= 1
    finally:
        queue.stop()
        runs_routes._outbound_retry_queue = original_queue


def test_recipes_endpoints_list_get_create() -> None:
    original_recipes = dict(runs_routes._recipes)
    try:
        client = TestClient(create_app())

        listed = client.get("/api/v1/runs/recipes")
        assert listed.status_code == 200
        assert "recipes" in listed.json()
        assert any(r["id"] == "test-hardening" for r in listed.json()["recipes"])

        fetched = client.get("/api/v1/runs/recipes/test-hardening")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == "test-hardening"

        created = client.post(
            "/api/v1/runs/recipes",
            json={
                "id": "docs-refresh",
                "name": "Docs Refresh",
                "description": "Refresh docs around a module",
                "goal_template": "Improve docs for {module_name}",
                "context_template": "priority={priority}",
                "tags": ["docs"],
            },
        )
        assert created.status_code == 200
        assert created.json()["id"] == "docs-refresh"

        fetched_new = client.get("/api/v1/runs/recipes/docs-refresh")
        assert fetched_new.status_code == 200
        assert fetched_new.json()["name"] == "Docs Refresh"
    finally:
        runs_routes._recipes.clear()
        runs_routes._recipes.update(original_recipes)


def test_create_run_with_recipe_renders_goal_and_context(tmp_path: Path) -> None:
    original_orchestrator = runs_routes._orchestrator
    original_recipes = dict(runs_routes._recipes)
    runs_routes._orchestrator = build_orchestrator()
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/runs",
            json={
                "goal": "placeholder",
                "repo_path": str(tmp_path),
                "recipe_id": "test-hardening",
                "recipe_inputs": {"target_area": "memory", "priority": "high"},
                "requested_by": "recipe-user",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["goal"] == "Harden tests for memory and summarize gaps"
        assert payload["id"].startswith("run_")
    finally:
        runs_routes._recipes.clear()
        runs_routes._recipes.update(original_recipes)
        runs_routes._orchestrator = original_orchestrator


def test_create_run_with_recipe_loads_executable_actions(tmp_path: Path) -> None:
    original_orchestrator = runs_routes._orchestrator
    original_recipes = dict(runs_routes._recipes)
    runs_routes._orchestrator = build_orchestrator()
    try:
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/runs",
            json={
                "goal": "placeholder",
                "repo_path": str(tmp_path),
                "recipe_id": "discord",
                "recipe_inputs": {
                    "focus": "api",
                    "priority": "high",
                    "constraints": "none",
                },
                "requested_by": "recipe-user",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["goal"] == "Execute the Discord workflow for this repository and summarize outcomes"
        assert len(payload["pending_actions"]) == 2
        assert payload["pending_actions"][0]["action_type"] == "command"
        assert payload["pending_actions"][0]["description"] == "Run baseline checks for Discord"
        assert payload["pending_actions"][1]["action_type"] == "edit"
        assert payload["pending_actions"][1]["file_path"].endswith("/recipe_outputs/discord_summary.md")
        assert any(evt["event"] == "recipe_actions_loaded" for evt in payload["timeline"])
    finally:
        runs_routes._recipes.clear()
        runs_routes._recipes.update(original_recipes)
        runs_routes._orchestrator = original_orchestrator
