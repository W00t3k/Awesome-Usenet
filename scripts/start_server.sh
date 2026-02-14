#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PORT="${1:-8443}"
HOST="${HOST:-127.0.0.1}"
UVICORN_BIN="$ROOT_DIR/.venv/bin/uvicorn"
LOG_FILE="$ROOT_DIR/server-${PORT}.log"
PID_FILE="$ROOT_DIR/.server-${PORT}.pid"

if [[ ! -x "$UVICORN_BIN" ]]; then
  echo "Missing uvicorn in .venv: $UVICORN_BIN"
  echo "Create/install venv first, then retry."
  exit 1
fi

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

if command -v lsof >/dev/null 2>&1; then
  PORT_PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN || true)"
  if [[ -n "$PORT_PIDS" ]]; then
    echo "$PORT_PIDS" | xargs kill || true
    sleep 1
  fi
fi

nohup "$UVICORN_BIN" app.main:app --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
NEW_PID="$!"
echo "$NEW_PID" > "$PID_FILE"

echo "Started app.main:app on http://$HOST:$PORT"
echo "PID: $NEW_PID"
echo "Log: $LOG_FILE"
