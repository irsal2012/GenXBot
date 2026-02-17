# GenXBot (OpenClaw-style Autonomous Coding App)

This app is scaffolded in `applications/genxbot` and now wired to **GenXAI** primitives:

- `AgentFactory` + `AgentRuntime` for planner/executor/reviewer agents
- `MemorySystem` for per-run memory context
- `ToolRegistry` + built-in tools for tool-available execution context
- `CriticReviewFlow` for reviewer feedback loop

👉 New: Full usage/tutorial doc: [`USAGE_GUIDE.md`](./USAGE_GUIDE.md)

👉 New: GenXBot vs OpenClaw comparison: [`COMPARISON_OPENCLAW.md`](./COMPARISON_OPENCLAW.md)

👉 New: First-time local setup checklist: [`FIRST_TIME_SETUP.md`](./FIRST_TIME_SETUP.md)

## Structure

```text
applications/genxbot/
  backend/
    app/
      api/routes_runs.py
      services/{orchestrator,policy,store}.py
      config.py
      schemas.py
      main.py
    tests/test_orchestrator.py
    requirements.txt
  frontend/
    src/{App.tsx,main.tsx,index.css}
    index.html
    package.json
    tsconfig*.json
    vite.config.ts
```

## Backend quick start

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Frontend quick start

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/frontend
npm install
npm run dev
```

## Global CLI install (Phase 7A)

GenXBot now includes a global-installable CLI scaffold under `applications/genxbot/cli`.

### Local/global install from this repo

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/cli
npm install -g .
```

Then run:

```bash
genxbot onboard
# optional daemon install on macOS/Linux
genxbot onboard --install-daemon
```

### Intended npm publish flow

After publishing this package to npm (name currently `genxbot`), users can install like:

```bash
npm install -g genxbot@latest
# or: pnpm add -g genxbot@latest
```

Detailed release/publish instructions:

- [`applications/genxbot/cli/PUBLISHING.md`](./cli/PUBLISHING.md)

## API

- `POST /api/v1/runs` create autonomous coding run
- `GET /api/v1/runs/recipes` list available recipes
- `GET /api/v1/runs/recipes/{recipe_id}` get recipe details
- `POST /api/v1/runs/recipes` create recipe (admin)
- `GET /api/v1/runs` list runs
- `GET /api/v1/runs/{run_id}` run details
- `POST /api/v1/runs/{run_id}/approval` approve/reject proposed action
- `POST /api/v1/runs/channels/{channel}` ingest normalized channel event (Phase 1: `slack`, `telegram`)
- `GET /api/v1/runs/channels/{channel}/trust-policy` read trust policy
- `PUT /api/v1/runs/channels/{channel}/trust-policy` update trust policy (`pairing`/`open`, allowlist)
- `GET /api/v1/runs/channels/{channel}/pairing/pending` list pending pairing codes
- `POST /api/v1/runs/channels/{channel}/pairing/approve` approve pairing code
- Channel command UX (message text): `/run`, `/status`, `/approve`, `/reject`
- `GET /api/v1/runs/channels/sessions` inspect channel session → run mappings
- `GET /api/v1/runs/channels/metrics` channel observability counters
- `GET /api/v1/runs/channels/{channel}/maintenance` get channel maintenance mode
- `PUT /api/v1/runs/channels/{channel}/maintenance` update maintenance mode (admin protected)
- `GET /api/v1/runs/channels/outbound-retry` outbound retry/dead-letter snapshot
- `GET /api/v1/runs/channels/outbound-retry/deadletters` list dead-letter jobs
- `POST /api/v1/runs/channels/outbound-retry/replay/{job_id}` replay a dead-letter job
- `GET/PUT /api/v1/runs/channels/approver-allowlist` command approver admin controls
- `GET /api/v1/runs/channels/admin-audit` list admin mutation audit entries
- `GET /api/v1/runs/channels/admin-audit/stats` admin audit retention stats
- `POST /api/v1/runs/channels/admin-audit/clear` clear admin audit log (admin protected)
- `GET /api/v1/runs/channels/idempotency-cache` idempotency cache stats (admin protected)
- `POST /api/v1/runs/channels/idempotency-cache/clear` clear idempotency cache (admin protected)
- `GET /api/v1/runs/queue/health` queue worker and backlog health snapshot
- `POST /api/v1/runs/channels/{channel}` supports optional `x-idempotency-key` header for dedupe

### Recipes (Phase 7B)

GenXBot now supports **Recipes** (reusable run templates) as an alternative to “skills”.

You can create runs with:

- `recipe_id`
- `recipe_inputs` (used to render recipe templates)

Example:

```json
{
  "goal": "placeholder",
  "repo_path": "/path/to/repo",
  "recipe_id": "test-hardening",
  "recipe_inputs": {
    "target_area": "memory",
    "priority": "high"
  }
}
```

### Admin security headers (for protected endpoints when `ADMIN_API_TOKEN` is set)

- `x-admin-token`: must match configured admin token
- `x-admin-actor`: operator identity
- `x-admin-role`: `viewer|executor|approver|admin` (role-checked per endpoint)

### Idempotency cache controls (Phase 6C)

Config keys:

- `CHANNEL_IDEMPOTENCY_CACHE_TTL_SECONDS` (default `900`)
- `CHANNEL_IDEMPOTENCY_CACHE_MAX_ENTRIES` (default `1000`)

Behavior:

- Entries expire by TTL and are pruned on access/write.
- Cache also enforces max-size by evicting oldest entries.

### Admin audit retention controls (Phase 6D)

Config key:

- `ADMIN_AUDIT_MAX_ENTRIES` (default `5000`)

Behavior:

- Admin audit log is now bounded (oldest entries are evicted automatically).
- Use `/channels/admin-audit/stats` to monitor current size and cap.
- Use `/channels/admin-audit/clear` for controlled admin resets.

### Channel maintenance mode (Phase 6E)

Per-channel operational switch to temporarily block new channel ingests:

- Supported channels: `slack`, `telegram`
- When enabled, inbound events return a maintenance response (`command: maintenance`) and skip run creation.
- State updates are admin-audited (`channel_maintenance_update`).

## Notes

- If `OPENAI_API_KEY` is present, GenXAI runtime executes live planner/executor/reviewer pipeline.
- If key is missing or runtime fails, flow falls back to deterministic proposal while preserving GenXAI wiring.
- Approval gates remain active via `SafetyPolicy`.
