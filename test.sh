#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "\n\033[36m🧪 Running Bitget S2 Divergent Agent Desk Test Suite...\033[0m"

echo -e "\n\033[33m[1/2] Running Risk Gate Smoke Test...\033[0m"
python scripts/smoke_risk.py

echo -e "\n\033[33m[2/2] Running Paper Shadow Book Smoke Test...\033[0m"
python scripts/smoke_paper.py

echo -e "\n\033[32m✅ Test suite execution complete.\033[0m"
