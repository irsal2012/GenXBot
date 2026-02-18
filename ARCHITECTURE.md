# GenXBot Architecture

GenXBot is an OpenClaw-style autonomous coding application built on **GenXAI**, an agentic AI framework that supplies planners, executors, reviewers, memory, and tool orchestration. GenXBot wraps that framework with a FastAPI backend, a React (Vite) control UI, and a Node-based CLI for onboarding and daemon setup. The system is optimized for **plan → approval → execution** workflows with explicit safety gates.

## Goals & Design Principles

- **Approval-first automation**: all potentially unsafe actions require explicit approval.
- **Multi-channel ingestion**: web UI, Slack, Telegram, and connector triggers can all create runs.
- **Observability & governance**: audit trails, trust policies, maintenance mode, and retry queues.
- **Pluggable AI pipeline**: GenXAI planner/executor/reviewer agents with memory and tools.

## High-Level Components

```
┌─────────────┐    HTTP/API     ┌────────────────────────────┐
│  Frontend   │  ───────────▶   │  FastAPI Backend           │
│  (React UI) │                 │  /api/v1/runs              │
└─────────────┘                 └──────────┬────────────────┘
        ▲                                   │
        │                                   │ Orchestrator + Services
        │                                   ▼
┌─────────────┐    Webhooks     ┌────────────────────────────┐
│ Slack/      │  ───────────▶   │  Channel Adapters          │
│ Telegram    │                 │  Trust/Outbound/Queue      │
└─────────────┘                 └──────────┬────────────────┘
                                           │
                                           │ Recipe Lookup
                                           ▼
                              ┌───────────────────────────────┐
                              │ Recipes Library                │
                              │ backend/app/recipes/*          │
                              └──────────┬────────────────────┘
                                           │
                                           ▼
                                  ┌────────────────────────────┐
                                  │ GenXAI Agentic Framework    │
                                  │ Planner/Executor/Reviewer   │
                                  │ Memory + Tool Registry      │
                                  └────────────────────────────┘
```

## Backend Architecture (FastAPI)

**Entry point**: `backend/app/main.py` creates the FastAPI app, configures CORS, and mounts `/api/v1` routes.

**Key routing module**: `backend/app/api/routes_runs.py`

### Core Services

- **GenXBotOrchestrator** (`app/services/orchestrator.py`)
  - Creates and manages autonomous runs.
  - Prepares a per-run sandbox workspace (optional).
  - Builds GenXAI stack: `AgentFactory`, `AgentRuntime`, `CriticReviewFlow`, `MemorySystem`, and `ToolRegistry`.
  - Generates plan steps + proposed actions, and applies safety policy gates.
  - Executes approved actions via `ActionExecutor`.

- **RunStore** (`app/services/store.py`)
  - Persists run state and audit logs.
  - Backend supports in-memory or SQLite depending on configuration.

- **SafetyPolicy** (`app/services/policy.py`)
  - Determines whether actions require approval and whether commands are safe.
  - Enforces approver role checks.

- **Channel Services**
  - `ChannelTrustService`: pairing codes, allowlists, DM policy.
  - `ChannelSessionService`: maps channel conversation sessions to run IDs.
  - `ChannelOutboundService`: delivers outbound messages to Slack/Telegram.
  - `ChannelObservabilityService`: metrics, trace IDs, replay detection.
  - `OutboundRetryQueueService`: retries failed outbound deliveries + dead-letter queue.
  - `WebhookSecurityService`: validates Slack/Telegram signatures and replay windows.

### API Surface (selected)

- **Runs**: `POST /runs`, `GET /runs`, `GET /runs/{id}`
- **Approvals**: `POST /runs/{id}/approval`
- **Rerun failed steps**: `POST /runs/{id}/rerun-failed-step`
- **Metrics**: `GET /runs/metrics`
- **Recipes**: `GET/POST /runs/recipes`
- **Queue health**: `GET /runs/queue/health`
- **Channels**: `/runs/channels/{channel}` for ingest, trust policy, pairing, maintenance mode, idempotency cache, retry queues.

### Run Lifecycle (Backend)

1. **Ingest**: UI / API / channel webhook creates a `RunTaskRequest`.
2. **Orchestrate**: `GenXBotOrchestrator.create_run()` builds plan steps and proposed actions.
3. **Approval**: unsafe actions are gated by `SafetyPolicy`.
4. **Execute**: approved actions are run via `ActionExecutor` and results stored as artifacts.
5. **Complete**: run status updates to `completed` when all actions are resolved.

## GenXAI Runtime Stack (Agentic Framework)

GenXBot delegates autonomous reasoning to GenXAI. The GenXBot orchestrator (not a GenXAI-provided orchestrator) builds a GenXAI stack per run and uses it as the **agentic AI framework** that generates plans, proposed actions, and reviews:

- **Agents**: planner, executor, reviewer (default model: `gpt-4`).
- **Memory**: `MemorySystem` supports Redis/SQLite/graph backends when configured (graph uses Neo4j when enabled).
- **Tools**: uses `ToolRegistry` with built-in GenXAI tools (directory scan, file read/write, code execution, regex, validation).
- **Review Loop**: `CriticReviewFlow` runs executor + reviewer for risk feedback.

If `OPENAI_API_KEY` is missing, the pipeline falls back to deterministic behavior while retaining the GenXAI wiring.

> **Note:** GenXBot does not use a GenXAI “orchestrator” service. It defines its own `GenXBotOrchestrator` that wraps GenXAI agents and optionally connects the GenXAI `MemorySystem` to Redis/SQLite/Neo4j for graph-backed memory.

### How GenXBot Uses GenXAI

1. **Run ingestion** → GenXBot captures the goal/context and provisions a GenXAI stack.
2. **Planning** → GenXAI planner proposes an execution plan.
3. **Action proposals** → GenXAI executor suggests candidate actions.
4. **Review** → GenXAI reviewer (CriticReviewFlow) flags risk and recommendations.
5. **Approval gates** → GenXBot’s `SafetyPolicy` enforces approvals before execution.
6. **Execution** → GenXBot executes approved actions and logs artifacts/timeline events.

### Future Integration with a GenXAI Orchestrator

If a GenXAI-native orchestrator is introduced later, the recommended integration pattern is:

1. **Adapter layer (preferred)**: keep GenXBot’s `GenXBotOrchestrator` as the app-level controller, and call the GenXAI orchestrator for plan/action generation. GenXBot would still own approvals, audit logs, channel policies, retries, and storage.
2. **Extension (only if needed)**: modify or extend the GenXAI orchestrator **only** if it lacks the hooks needed for approval gates, audit events, or lifecycle callbacks.

This keeps GenXBot’s governance and ops controls intact while still leveraging GenXAI’s agentic pipeline.

## Frontend Architecture (React + Vite)

**Entry**: `frontend/src/main.tsx` renders `<App />`.

**App**: `frontend/src/App.tsx`

- Provides a control dashboard for runs, approvals, and artifacts.
- Includes “chat” mode that calls `/api/v1/runs/channels/web` for conversational queries.
- Supports trigger simulation for connectors (GitHub/Jira/Slack).
- Includes admin panels for trust policies, pairing codes, allowlists, retry queue, and metrics.

The frontend calls the API base from `VITE_API_BASE` (defaults to `http://localhost:8000`).

## CLI Architecture

**Entry**: `cli/bin/genxbot.js`

- `genxbot onboard` creates `~/.genxbot/.env` and log folders.
- Optional `--install-daemon` installs a user-level daemon on macOS (LaunchAgent) or Linux (systemd).
- CLI is designed for global npm installation and local development onboarding.

## Configuration & Security

Key config values are in `backend/app/config.py` and environment variables:

- `OPENAI_API_KEY`: enables live GenXAI runtime.
- `ADMIN_API_TOKEN`: required for protected admin endpoints.
- `CHANNEL_WEBHOOK_SECURITY_ENABLED`: validates webhooks.
- `CHANNEL_IDEMPOTENCY_CACHE_*`: dedupes channel requests.
- `ADMIN_AUDIT_MAX_ENTRIES`: bounds admin audit retention.

Admin endpoints require headers:

- `x-admin-token`
- `x-admin-actor`
- `x-admin-role`

## Data & Observability

- **Run Store**: retains runs, timeline events, actions, and artifacts.
- **Audit Log**: immutable history of admin/user decisions.
- **Channel Metrics**: inbound/outbound counts, replay blocks.
- **Queue Health**: retry backlogs and worker liveness.

## Recipes Library

Recipes live under `backend/app/recipes/*/recipe.json` and allow reusable run templates:

- `goal_template`, `context_template`
- `action_templates` for precomputed edits/commands

Recipes are resolved in `routes_runs.py` via `_resolve_recipe_request()`.

## Deployment Notes

- Backend: `uvicorn app.main:app --reload --port 8000`
- Frontend: `npm run dev` (Vite)
- CLI: `npm install -g ./cli`

## Suggested Next Docs

- Add sequence diagrams for: run creation, approval/execution, channel pairing.
- Include a configuration matrix (dev/staging/prod). 
- See [GENXAI_DESIGN_NOTE.md](./GENXAI_DESIGN_NOTE.md) for suggested GenXAI improvements.