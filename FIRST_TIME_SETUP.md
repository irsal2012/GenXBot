# GenXBot First-Time Setup (Step-by-Step)

This guide is a copy-paste checklist for first-time users to get GenXBot running locally.

It includes two common starting points:

- **Path A:** You already installed the CLI globally (`npm install -g genxbot`)
- **Path B:** You are starting directly from repository clone

---

## 1) Prerequisites

Make sure these are installed:

- Python 3.11+
- Node.js 18+
- npm
- git

---

## 2) Path A — After CLI install (`npm install -g genxbot`)

If you already installed the CLI globally, do this first:

```bash
genxbot help
genxbot onboard
```

Optional daemon setup (macOS/Linux):

```bash
genxbot onboard --install-daemon
```

This creates:

- `~/.genxbot/.env`
- `~/.genxbot/logs/`

### Important current behavior

The current CLI is an onboarding utility. To actually run GenXBot backend/frontend, users should also have the GenXAI repository available locally (next step).

---

## 3) Clone and enter the repository (required to run backend/frontend)

```bash
git clone https://github.com/genexsus-ai/genxai.git
cd /Users/irsalimran/Desktop/GenXAI-OSS
```

---

## 4) Backend setup

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 5) Configure environment variables (`.env`)

In `applications/genxbot/backend/.env`, set at minimum:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

Optional for protected admin endpoints:

```env
ADMIN_API_TOKEN=your_admin_token_here
```

You can create/update it quickly with:

```bash
cat > /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/backend/.env <<'EOF_ENV'
OPENAI_API_KEY=your_openai_api_key_here
# ADMIN_API_TOKEN=your_admin_token_here
EOF_ENV
```

---

## 6) Start backend (terminal 1)

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Backend URL:

- `http://localhost:8000`

Keep this terminal running.

---

## 7) (Optional) Start frontend dashboard (terminal 2)

If you want a web UI for run creation, approvals, timeline, artifacts, and metrics:

```bash
cd /Users/irsalimran/Desktop/GenXAI-OSS/applications/genxbot/frontend
npm install
npm run dev
```

Frontend URL:

- `http://localhost:5173`

> Frontend is optional. GenXBot can be used from API/CLI/channels only.

---

## 8) Verify backend is up (terminal 3)

```bash
curl http://localhost:8000/api/v1/runs
```

If you get JSON back (even an empty list), backend is working.

---

## 9) Create your first run (API)

```bash
curl -X POST http://localhost:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Add tests for memory manager and summarize gaps",
    "repo_path": "/Users/irsalimran/Desktop/GenXAI-OSS",
    "requested_by": "first-user"
  }'
```

Copy the returned `run.id`.

---

## 10) Check run status

```bash
curl http://localhost:8000/api/v1/runs/<run_id>
```

Replace `<run_id>` with your real run ID.

---

## 11) Approve/reject pending actions

If the run requires approval, submit a decision:

```bash
curl -X POST http://localhost:8000/api/v1/runs/<run_id>/approval \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "<action_id>",
    "approve": true,
    "comment": "Looks safe",
    "actor": "first-user",
    "actor_role": "approver"
  }'
```

---

## 12) Optional UI workflow

If frontend is running:

1. Open `http://localhost:5173`
2. Enter Goal + Repository Path
3. Click **Create Run**
4. Use **Pending Actions** to approve/reject
5. Review timeline/artifacts/metrics

---

## 13) Stop services

- Backend terminal: `Ctrl + C`
- Frontend terminal: `Ctrl + C`

---

## Troubleshooting quick checks

- Backend not reachable: confirm `uvicorn` is running on port `8000`
- Frontend can’t talk to backend: check backend URL and CORS (`http://localhost:5173`)
- Admin endpoint returns 401/403: verify `ADMIN_API_TOKEN` and role headers

---

## Security note

- Never commit real API keys to Git.
- If a key was exposed, rotate/revoke it immediately and replace it.
