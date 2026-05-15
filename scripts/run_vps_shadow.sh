#!/usr/bin/env bash
# Shadow-mode runner for the Kraken Alpha Agent.
#
# Runs the agent loop in dry_run against the real Kraken CLI. No live
# orders are placed, ever. This script intentionally does NOT touch
# .env: the operator owns secrets management.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [ ! -d ".venv" ]; then
  echo "ERROR: .venv missing — create it first (see docs/VPS_RUNBOOK.md)." >&2
  exit 1
fi
# shellcheck disable=SC1091
. .venv/bin/activate

PROFILE="${KRAKEN_ALPHA_PROFILE:-aggressive_competition}"
export KRAKEN_ALPHA_PROFILE="${PROFILE}"

# Force dry_run on the shadow runner regardless of what the user has in
# their env. This script REFUSES to start in live mode.
export TRADING_MODE="dry_run"
export LIVE_TRADING="false"
export ALLOW_LIVE_ORDERS="false"

cat <<'BANNER'
============================================================
SHADOW RUN — Kraken Alpha Agent
- TRADING_MODE=dry_run (forced)
- LIVE_TRADING=false (forced)
- ALLOW_LIVE_ORDERS=false (forced)
- No order will be sent to Kraken.
BANNER
echo "Active profile: ${PROFILE}"
echo "Project root:   ${ROOT}"
echo "============================================================"

exec python scripts/run_agent_loop.py
