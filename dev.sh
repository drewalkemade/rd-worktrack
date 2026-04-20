#!/usr/bin/env bash
# dev.sh — Start the R&D Controls Payroll workboard (backend + frontend).
#
# Usage:
#   ./dev.sh          start both servers (Ctrl-C to stop both)
#   ./dev.sh --kill   kill any already-running instances on ports 8000 / 5173

set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── kill mode ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--kill" ]]; then
  echo "Killing processes on ports 8000 and 5173..."
  fuser -k 8000/tcp 2>/dev/null && echo "  killed port 8000" || echo "  nothing on port 8000"
  fuser -k 5173/tcp 2>/dev/null && echo "  killed port 5173" || echo "  nothing on port 5173"
  exit 0
fi

# ── clean up stale processes before starting ─────────────────────────────────
fuser -k 8000/tcp 2>/dev/null && echo "Cleared stale process on port 8000" || true
fuser -k 5173/tcp 2>/dev/null && echo "Cleared stale process on port 5173" || true

# ── activate virtualenv ──────────────────────────────────────────────────────
if [[ ! -f "$PROJECT_ROOT/.venv/bin/activate" ]]; then
  echo "ERROR: .venv not found at $PROJECT_ROOT/.venv"
  echo "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
source "$PROJECT_ROOT/.venv/bin/activate"

# ── backend ──────────────────────────────────────────────────────────────────
echo "Starting backend  → http://localhost:8000"
cd "$PROJECT_ROOT"
uvicorn payroll_app.api.main:app --reload --port 8000 &
BACKEND_PID=$!

# ── frontend ─────────────────────────────────────────────────────────────────
if [[ ! -d "$PROJECT_ROOT/payroll_app/frontend/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  (cd "$PROJECT_ROOT/payroll_app/frontend" && npm install)
fi

echo "Starting frontend → http://localhost:5173"
# setsid puts npm + vite in their own process group so we can kill the whole tree
cd "$PROJECT_ROOT/payroll_app/frontend"
setsid npm run dev &
FRONTEND_PID=$!

echo ""
echo "Both servers running. Press Ctrl-C to stop both."
echo "  Backend  PID: $BACKEND_PID"
echo "  Frontend PID: $FRONTEND_PID"
echo ""

# ── shutdown trap ─────────────────────────────────────────────────────────────
cleanup() {
  echo ""
  echo "Stopping servers..."

  # Kill the backend and its reloader children by process group
  kill -- "-$BACKEND_PID"  2>/dev/null || true
  kill -- "-$FRONTEND_PID" 2>/dev/null || true

  # Wait for them to finish so their output doesn't race past the prompt
  wait "$BACKEND_PID"  2>/dev/null || true
  wait "$FRONTEND_PID" 2>/dev/null || true

  echo "Done."
  exit 0
}
trap cleanup INT TERM

# Disable errexit for the wait so a dying child doesn't skip cleanup
set +e
wait
