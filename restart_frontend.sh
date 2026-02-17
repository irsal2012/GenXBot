#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_FILE="$FRONTEND_DIR/vite.log"
PORT="5173"

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "❌ Frontend directory not found: $FRONTEND_DIR"
  exit 1
fi

if [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
  echo "❌ package.json not found in frontend directory"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "❌ npm is not installed or not on PATH"
  exit 1
fi

echo "🔄 Restarting frontend dev server on port $PORT..."

# Stop currently running frontend process(es) bound to the configured port.
EXISTING_PIDS="$(lsof -ti tcp:$PORT || true)"
if [[ -n "$EXISTING_PIDS" ]]; then
  echo "⏹ Stopping existing process(es): $EXISTING_PIDS"
  kill $EXISTING_PIDS || true
  sleep 1
fi

cd "$FRONTEND_DIR"

nohup npm run dev -- --host 127.0.0.1 --port "$PORT" > "$LOG_FILE" 2>&1 &
NEW_PID=$!

echo "✅ Frontend restarted. PID: $NEW_PID"
echo "📝 Logs: $LOG_FILE"

SITE_URL="http://127.0.0.1:$PORT"
echo "🌐 Opening frontend in browser: $SITE_URL"
open "$SITE_URL"