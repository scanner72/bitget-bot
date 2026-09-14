#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting Divergent Agent Desk..."

python_bin() {
  if [ -x ".venv/bin/python" ]; then
    echo ".venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    command -v python
  fi
}

USE_DOCKER=1
if ! docker info >/dev/null 2>&1; then
  echo "Docker not running — using local Python."
  USE_DOCKER=0
else
  echo "Docker is up."
fi

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "Created .env from .env.example — add Bitget Demo keys (and Groq if AGENT_MODE=llm)."
  else
    echo "Missing .env and .env.example"
    exit 1
  fi
fi

if [ "$USE_DOCKER" -eq 1 ]; then
  docker compose up -d --build
else
  PY="$(python_bin)"
  mkdir -p data
  echo "API + desk via $PY"
  nohup "$PY" scripts/run_api.py >>data/api.log 2>&1 &
  nohup "$PY" scripts/run_signal_loop.py --poll >>data/desk.log 2>&1 &
fi

ok=0
for _ in $(seq 1 30); do
  sleep 1
  if curl -fsS "http://127.0.0.1:8080/health" | grep -q '"ok": true\|"ok":true'; then
    ok=1
    break
  fi
done

if [ "$ok" -eq 1 ]; then
  echo "Health ok  http://127.0.0.1:8080"
else
  echo "Dashboard not healthy yet. Check: docker compose logs -f"
  echo "Expected GET /health -> { ok: true, exec_mode: hub_demo }"
  exit 1
fi
