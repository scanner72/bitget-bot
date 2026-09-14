#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "\n\033[36m🚀 Starting Bitget S2 Divergent Agent Desk...\033[0m"

# 1. Verify Docker Daemon
echo -e "\033[33m[1/4] Checking Docker status...\033[0m"
USE_DOCKER=1
if ! docker info >/dev/null 2>&1; then
    echo -e "\033[33m  ⚠️ Docker daemon not running. Falling back to local Python runtime.\033[0m"
    USE_DOCKER=0
else
    echo -e "\033[32m  ✅ Docker daemon is running.\033[0m"
fi

# 2. Verify Environment File
echo -e "\033[33m[2/4] Verifying environment configuration...\033[0m"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "\033[33m  ⚠️ Created default .env from .env.example. Add your Bitget Demo keys.\033[0m"
    else
        echo -e "\033[31m  ❌ Error: Neither .env nor .env.example found.\033[0m"
        exit 1
    fi
else
    echo -e "\033[32m  ✅ .env configuration found.\033[0m"
fi

# 3. Launch Services
if [ "$USE_DOCKER" -eq 1 ]; then
    echo -e "\033[33m[3/4] Launching Docker Compose stack...\033[0m"
    docker compose up -d
else
    echo -e "\033[33m[3/4] Launching background Python processes...\033[0m"
    nohup python scripts/run_api.py >/dev/null 2>&1 &
    nohup python scripts/run_signal_loop.py --poll >/dev/null 2>&1 &
fi

# 4. Status Output
echo -e "\n\033[33m[4/4] Verifying services...\033[0m"
sleep 4

echo -e "\033[36m"
cat << "EOF"
==============================================================================
✨ Bitget S2 Divergent Agent Desk is LIVE!
==============================================================================

  💻 Web Dashboard:     http://127.0.0.1:8080
  📡 REST API Health:   http://127.0.0.1:8080/health
  📈 Signal Candidates: http://127.0.0.1:8080/candidates
  💼 Active Positions:  http://127.0.0.1:8080/positions

To view real-time Docker logs:
  docker compose logs -f

To stop all containers:
  docker compose down
==============================================================================
EOF
echo -e "\033[0m"
