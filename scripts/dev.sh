#!/usr/bin/env bash
# Boot the full REZN stack for a local demo:
#   - API (FastAPI)   -> http://localhost:8000
#   - Control Room UI -> http://localhost:3000
# Ctrl-C stops both. Reads secrets from .env (API) and .env.local (UI copilot).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and add WANDB_API_KEY / REDIS_URL first." >&2
  exit 1
fi

[[ -d node_modules ]] || { echo "→ installing UI deps (npm install)…"; npm install; }

API_PID=""
cleanup() { [[ -n "$API_PID" ]] && kill "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "→ Starting API on :8000 (logs: /tmp/rezn-api.log)…"
uv run --env-file .env uvicorn rezn_ai.api.main:app --port 8000 >/tmp/rezn-api.log 2>&1 &
API_PID=$!

printf "→ Waiting for API"
for _ in $(seq 1 90); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then echo " ✓ ready"; break; fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo; echo "API exited early — last lines:" >&2; tail -n 20 /tmp/rezn-api.log >&2; exit 1
  fi
  printf "."; sleep 1
done

echo "→ Control Room on http://localhost:3000  (Ctrl-C stops everything)"
npm run dev
