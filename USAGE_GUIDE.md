# GenXBot Usage Guide

This guide explains how to run GenXBot end-to-end, use the UI/API, and exercise common operator workflows.

---

## 1) What GenXBot does

GenXBot is an autonomous coding assistant app built on GenXAI.

It supports:

- creating coding runs from API/UI/channel messages
- plan + action workflow with approval gates
- channel-based commands (`/run`, `/status`, `/approve`, `/reject`)
- admin controls (allowlists, trust policies, audit, maintenance mode)
- operational controls (idempotency cache, retry queue, health checks)

---

## 2) Quick start (local)

### Backend

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/frontend
npm install
npm run dev
```

- Backend: `http://localhost:8000`
- Frontend: `http://localhost:5173`

---

## 3) Global CLI onboarding (optional)

If you installed the CLI globally:

```bash
genxbot onboard
```

Or with daemon setup (macOS/Linux):

```bash
genxbot onboard --install-daemon
```

This initializes:

- `~/.genxbot/.env`
- `~/.genxbot/logs/`

---

## 4) Minimal API flow examples

## 4.1 Create a run

```bash
curl -X POST http://localhost:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Add tests for memory manager and summarize gaps",
    "repo_path": "/Users/irsalimran/Desktop/GenXAI-OSS",
    "requested_by": "demo-user"
  }'
```

## 4.2 List runs

```bash
curl http://localhost:8000/api/v1/runs
```

## 4.3 Get run details

```bash
curl http://localhost:8000/api/v1/runs/<run_id>
```

## 4.4 Approve/reject action

```bash
curl -X POST http://localhost:8000/api/v1/runs/<run_id>/approval \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "<action_id>",
    "approve": true,
    "comment": "Looks safe",
    "actor": "ops-user",
    "actor_role": "approver"
  }'
```

---

## 5) Channel command examples

### Supported commands

- `/run <goal>`
- `/status [run_id]`
- `/approve <action_id> [run_id]`
- `/reject <action_id> [run_id]`

### Slack ingest example

```bash
curl -X POST http://localhost:8000/api/v1/runs/channels/slack \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "slack",
    "event_type": "message",
    "default_repo_path": "/Users/irsalimran/Desktop/GenXAI-OSS",
    "payload": {
      "event": {
        "type": "message",
        "user": "U123",
        "channel": "C999",
        "text": "/run improve CI flakiness report"
      }
    }
  }'
```

### Telegram ingest example

```bash
curl -X POST http://localhost:8000/api/v1/runs/channels/telegram \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "telegram",
    "event_type": "message",
    "default_repo_path": "/Users/irsalimran/Desktop/GenXAI-OSS",
    "payload": {
      "message": {
        "from": { "id": 5001 },
        "chat": { "id": -1001 },
        "text": "/status"
      }
    }
  }'
```

---

## 6) Operator/admin examples

When `ADMIN_API_TOKEN` is configured, protected endpoints require:

- `x-admin-token`
- `x-admin-actor`
- `x-admin-role` (`viewer|executor|approver|admin`)

### 6.1 Read admin audit

```bash
curl http://localhost:8000/api/v1/runs/channels/admin-audit \
  -H "x-admin-token: <token>" \
  -H "x-admin-actor: ops-reader" \
  -H "x-admin-role: approver"
```

### 6.2 Update channel maintenance mode (Phase 6E)

Enable:

```bash
curl -X PUT http://localhost:8000/api/v1/runs/channels/slack/maintenance \
  -H "Content-Type: application/json" \
  -H "x-admin-token: <token>" \
  -H "x-admin-actor: root-admin" \
  -H "x-admin-role: admin" \
  -d '{"enabled": true, "reason": "scheduled maintenance window"}'
```

Disable:

```bash
curl -X PUT http://localhost:8000/api/v1/runs/channels/slack/maintenance \
  -H "Content-Type: application/json" \
  -H "x-admin-token: <token>" \
  -H "x-admin-actor: root-admin" \
  -H "x-admin-role: admin" \
  -d '{"enabled": false, "reason": ""}'
```

### 6.3 Idempotency cache stats/clear (Phase 6C)

```bash
curl http://localhost:8000/api/v1/runs/channels/idempotency-cache \
  -H "x-admin-token: <token>" \
  -H "x-admin-actor: ops-reader" \
  -H "x-admin-role: approver"
```

```bash
curl -X POST http://localhost:8000/api/v1/runs/channels/idempotency-cache/clear \
  -H "x-admin-token: <token>" \
  -H "x-admin-actor: root-admin" \
  -H "x-admin-role: admin"
```

### 6.4 Admin audit stats/clear (Phase 6D)

```bash
curl http://localhost:8000/api/v1/runs/channels/admin-audit/stats \
  -H "x-admin-token: <token>" \
  -H "x-admin-actor: ops-reader" \
  -H "x-admin-role: approver"
```

```bash
curl -X POST http://localhost:8000/api/v1/runs/channels/admin-audit/clear \
  -H "x-admin-token: <token>" \
  -H "x-admin-actor: root-admin" \
  -H "x-admin-role: admin"
```

---

## 7) Reliability & health checks

### Queue health

```bash
curl http://localhost:8000/api/v1/runs/queue/health
```

### Outbound retry queue snapshot

```bash
curl http://localhost:8000/api/v1/runs/channels/outbound-retry
```

### Dead-letter list

```bash
curl http://localhost:8000/api/v1/runs/channels/outbound-retry/deadletters
```

---

## 8) Common troubleshooting

- `401 Invalid admin token`: wrong `x-admin-token`
- `403 Insufficient admin role`: role lower than endpoint requirement
- `400 Path channel and payload channel mismatch`: ensure URL channel matches JSON `channel`
- Channel ingest blocked unexpectedly: check maintenance mode endpoint for that channel
- Duplicate channel processing: use `x-idempotency-key` header and inspect cache stats

---

## 9) Suggested demo script (5-minute walkthrough)

1. Start backend/frontend.
2. Create run (`POST /runs`).
3. Approve one action.
4. Toggle Slack maintenance on and show blocked ingest.
5. Toggle maintenance off and show ingest succeeds.
6. Show admin audit entries and queue health.
