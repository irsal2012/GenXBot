#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
LOG_FILE="$BACKEND_DIR/uvicorn.log"
PORT="8000"

if [[ ! -d "$BACKEND_DIR" ]]; then
  echo "❌ Backend directory not found: $BACKEND_DIR"
  exit 1
fi

echo "🔄 Restarting backend on port $PORT..."

# Stop currently running backend process(es) bound to the configured port.
EXISTING_PIDS="$(lsof -ti tcp:$PORT || true)"
if [[ -n "$EXISTING_PIDS" ]]; then
  echo "⏹ Stopping existing process(es): $EXISTING_PIDS"
  # Intentionally unquoted to pass multiple PIDs as separate args.
  kill $EXISTING_PIDS || true
  sleep 1
fi

cd "$BACKEND_DIR"

# Prefer project virtual environment if available.
if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

nohup "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload > "$LOG_FILE" 2>&1 &
NEW_PID=$!

echo "✅ Backend restarted. PID: $NEW_PID"
echo "📝 Logs: $LOG_FILE"