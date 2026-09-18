#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

smokes=(
  scripts/smoke_signal.py
  scripts/smoke_candidate_log.py
  scripts/smoke_risk.py
  scripts/smoke_decide.py
  scripts/smoke_llm_decide.py
  scripts/smoke_paper.py
  scripts/smoke_account.py
  scripts/smoke_exits.py
  scripts/smoke_atr_rtoken.py
  scripts/smoke_pair_blocker.py
  scripts/smoke_symbols.py
  scripts/smoke_upnl.py
  scripts/smoke_tick_stops.py
  scripts/smoke_paper_fallback.py
  scripts/smoke_hub_leverage.py
  scripts/smoke_hub_price_scale.py
  scripts/smoke_reconcile.py
  scripts/smoke_chart.py
  scripts/smoke_export_paper_log.py
  scripts/verify_decision_log.py
)

echo "Smokes via $PY"
for s in "${smokes[@]}"; do
  echo "  $s"
  "$PY" "$s"
done
echo "All smokes passed."
