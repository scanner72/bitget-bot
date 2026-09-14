#!/usr/bin/env bash
set -e

REMOTE_HOST="${1:-10.10.10.11}"
REMOTE_USER="${2:-operator}"
REMOTE_PATH="${3:-/opt/bitget-bot}"
APP_PORT="${4:-8080}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "\n\033[36m🚀 Deploying Bitget S2 Divergent Agent Desk to ${REMOTE_HOST} (${REMOTE_USER})...\033[0m"

echo -e "\033[33m[1/4] Ensuring remote directory ${REMOTE_PATH}...\033[0m"
ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p ${REMOTE_PATH}"

echo -e "\033[33m[2/4] Packaging repository...\033[0m"
tar --exclude=".git" --exclude=".venv" --exclude="*__pycache__*" --exclude="*.pytest_cache*" --exclude="data/decisions.jsonl" -czf bitget_bot_deploy.tar.gz .
scp bitget_bot_deploy.tar.gz "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/"
ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_PATH} && tar -xzf bitget_bot_deploy.tar.gz && rm bitget_bot_deploy.tar.gz"
rm -f bitget_bot_deploy.tar.gz

echo -e "\033[33m[3/4] Launching Docker stack on remote host...\033[0m"
ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd ${REMOTE_PATH} && docker compose up -d --build"

echo -e "\033[33m[4/4] Verifying remote health...\033[0m"
sleep 5
echo -e "\033[32m✅ Deployment initiated successfully!\033[0m"
echo -e "\033[36mWeb Dashboard: http://${REMOTE_HOST}:${APP_PORT}\033[0m"
