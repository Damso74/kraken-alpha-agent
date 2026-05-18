#!/usr/bin/env bash
# Shadow-mode runner for the **hackathon xStocks dry-run session** on the VPS.
#
# Forces the ``shadow_xstocks_36h`` profile, the dry_run triple-block,
# and ``KRAKEN_CLI_TRANSPORT=auto`` (the wrapper picks the native Linux
# binary on the VPS). NO live order is ever placed: see
# src/execution._assert_not_dry_run for the in-process tripwire.
#
# Restart policy:
#   - On a non-zero exit from python, sleep with exponential backoff
#     (5s -> 30s -> 5min capped) and re-launch the loop.
#   - All stdout/stderr is mirrored to data/shadow_session.log.
#
# Intended workflow inside tmux::
#
#     tmux new -s kraken-shadow
#     bash scripts/run_vps_shadow_xstocks.sh
#     # Ctrl-b d to detach. tmux attach -t kraken-shadow to reattach.
#
# To stop cleanly, attach back and Ctrl+C once. The launcher catches
# Ctrl+C, writes a stop marker to data/shadow_session.log, and exits.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if [ ! -d ".venv" ]; then
  echo "ERROR: .venv missing - create it first (see docs/VPS_RUNBOOK.md)." >&2
  exit 1
fi
# shellcheck disable=SC1091
. .venv/bin/activate

# Force-clamp dry_run regardless of what the operator has in .env. This
# script REFUSES to start in any other mode.
export TRADING_MODE="dry_run"
export LIVE_TRADING="false"
export ALLOW_LIVE_ORDERS="false"
export KRAKEN_ALPHA_PROFILE="shadow_xstocks_36h"
export LOOP_INTERVAL_SECONDS="${LOOP_INTERVAL_SECONDS:-60}"
export KRAKEN_CLI_TRANSPORT="${KRAKEN_CLI_TRANSPORT:-auto}"

LOG_DIR="${ROOT}/data"
LOG_PATH="${LOG_DIR}/shadow_session.log"
META_PATH="${LOG_DIR}/shadow_session.json"
mkdir -p "${LOG_DIR}"

STARTED_AT_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
STARTED_AT_LOCAL="$(date +%Y-%m-%dT%H:%M:%S%z)"

# Metadata file consumed by scripts/monitor_shadow_session.py and
# scripts/export_shadow_session_for_submission.py to discover when the
# session started without grepping the log.
cat > "${META_PATH}" <<EOF
{
  "started_at_utc": "${STARTED_AT_UTC}",
  "started_at_local": "${STARTED_AT_LOCAL}",
  "profile": "shadow_xstocks_36h",
  "loop_interval_s": ${LOOP_INTERVAL_SECONDS},
  "log_file": "${LOG_PATH}",
  "pid": $$,
  "host": "$(hostname)",
  "repo_root": "${ROOT}",
  "kraken_cli_transport": "${KRAKEN_CLI_TRANSPORT}"
}
EOF

BANNER="============================================================
SHADOW XSTOCKS DRY-RUN - DO NOT SHUT DOWN
============================================================
started_at        : ${STARTED_AT_UTC} UTC
profile           : shadow_xstocks_36h
loop_interval_s   : ${LOOP_INTERVAL_SECONDS}
TRADING_MODE      : dry_run   (forced)
LIVE_TRADING      : false     (forced)
ALLOW_LIVE_ORDERS : false     (forced)
KRAKEN_CLI_TRANSPORT : ${KRAKEN_CLI_TRANSPORT}
log_file          : ${LOG_PATH}
host              : $(hostname)
repo_root         : ${ROOT}

NO LIVE ORDER WILL BE PLACED. Read-only Kraken CLI calls only
(ticker / ohlc / orderbook / trades / balance). Dry-run fills
are persisted to data/agent.sqlite for the post-run submission
export. The src/execution._assert_not_dry_run tripwire raises
DryRunMutationError if a refactor lets a dry_run request slip
through to a mutating CLI call.

Detach from tmux: Ctrl-b d
Stop cleanly    : attach back, then Ctrl+C
Live tail log   : tail -f ${LOG_PATH}
============================================================"

echo "${BANNER}"
echo "${BANNER}" >> "${LOG_PATH}"

# Restart-on-crash with exponential backoff.
BACKOFF=5
RESTART_COUNT=0
MAX_BACKOFF=300

trap 'echo "[$(date -u +%FT%TZ)] launcher trap: stopping" | tee -a "${LOG_PATH}"; exit 0' INT TERM

while true; do
  CYCLE_HEADER="[$(date -u +%FT%TZ)] starting agent loop (attempt $((RESTART_COUNT + 1)))"
  echo "${CYCLE_HEADER}" | tee -a "${LOG_PATH}"

  set +e
  python scripts/run_agent_loop.py 2>&1 | tee -a "${LOG_PATH}"
  EXIT_CODE=${PIPESTATUS[0]}
  set -e

  if [ "${EXIT_CODE}" -eq 0 ]; then
    STOP_MSG="[$(date -u +%FT%TZ)] agent loop exited cleanly (exit_code=0). Launcher stopping."
    echo "${STOP_MSG}" | tee -a "${LOG_PATH}"
    break
  fi

  RESTART_COUNT=$((RESTART_COUNT + 1))
  RESTART_MSG="[$(date -u +%FT%TZ)] agent loop crashed (exit_code=${EXIT_CODE}). Restart #${RESTART_COUNT} in ${BACKOFF}s."
  echo "${RESTART_MSG}" | tee -a "${LOG_PATH}"

  sleep "${BACKOFF}"

  if [ "${BACKOFF}" -lt "${MAX_BACKOFF}" ]; then
    BACKOFF=$((BACKOFF * 2))
    if [ "${BACKOFF}" -gt "${MAX_BACKOFF}" ]; then
      BACKOFF=${MAX_BACKOFF}
    fi
  fi
done

STOPPED_AT="$(date -u +%FT%TZ)"
echo "[${STOPPED_AT}] launcher exit. restart_count=${RESTART_COUNT}" | tee -a "${LOG_PATH}"
