#!/usr/bin/env bash
# Live micro-mode runner — refuses to start unless the operator has
# explicitly opted in. Always pair with a tmux session so a dropped SSH
# does not orphan the loop.
#
# Preconditions checked here (also enforced by scripts/live_preflight.py):
# 1. KRAKEN_ALPHA_PROFILE=micro_live_100eur
# 2. TRADING_MODE=live + LIVE_TRADING=true + ALLOW_LIVE_ORDERS=true (all three).
# 3. KRAKEN_API_KEY and KRAKEN_API_SECRET are non-empty.
# 4. data/validate_live_xstocks_latest.json exists.
#
# This script never modifies .env and never prints secret values.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [ ! -d ".venv" ]; then
  echo "ERROR: .venv missing — see docs/VPS_RUNBOOK.md." >&2
  exit 1
fi
# shellcheck disable=SC1091
. .venv/bin/activate

require_eq() {
  local name="$1" expected="$2" actual="${3:-}"
  if [ "${actual}" != "${expected}" ]; then
    echo "ERROR: ${name} must be '${expected}' (got '${actual:-<unset>}')." >&2
    exit 1
  fi
}

require_eq "KRAKEN_ALPHA_PROFILE" "micro_live_100eur" "${KRAKEN_ALPHA_PROFILE:-}"
require_eq "TRADING_MODE" "live" "${TRADING_MODE:-}"
require_eq "LIVE_TRADING" "true" "${LIVE_TRADING:-}"
require_eq "ALLOW_LIVE_ORDERS" "true" "${ALLOW_LIVE_ORDERS:-}"

if [ -z "${KRAKEN_API_KEY:-}" ] || [ -z "${KRAKEN_API_SECRET:-}" ]; then
  echo "ERROR: KRAKEN_API_KEY / KRAKEN_API_SECRET must be set." >&2
  exit 1
fi

if [ ! -f "data/validate_live_xstocks_latest.json" ]; then
  echo "ERROR: data/validate_live_xstocks_latest.json missing." >&2
  echo "Run 'python scripts/validate_live_xstocks.py' first." >&2
  exit 1
fi

cat <<'BANNER'
████████████████████████████████████████████████████████████
█                                                          █
█           LIVE MICRO RUN — REAL MONEY                    █
█                                                          █
█  - Max total exposure: 30 USD (enforced in profile)      █
█  - Max position size: 10 USD (enforced in profile)       █
█  - No shorting, no withdrawal, validate-only first run.  █
█  - Stop before Friday US close.                          █
█                                                          █
████████████████████████████████████████████████████████████
BANNER

# Optional dead-man's switch — best-effort, ignored on failure so a
# missing CLI cannot leave us hanging. If supported by your Kraken CLI
# build it cancels all open orders 60s after the last keep-alive call.
if command -v kraken >/dev/null 2>&1; then
  if kraken order cancel-after 60 -o json >/dev/null 2>&1; then
    echo "Dead-man's switch armed: kraken order cancel-after 60"
  else
    echo "Dead-man's switch unavailable on this CLI version — continuing."
  fi
fi

echo "Running final preflight (with --allow-live-env-check)..."
if ! python scripts/live_preflight.py --allow-live-env-check; then
  echo "ERROR: preflight failed. Aborting." >&2
  exit 1
fi

echo "Starting live agent loop. Detach with Ctrl-b d if inside tmux."
exec python scripts/run_agent_loop.py
