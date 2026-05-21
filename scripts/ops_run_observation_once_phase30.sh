#!/usr/bin/env bash
# Phase 30 — VPS/local observation once (cache refresh + daemon + reports).
# Usage: bash scripts/ops_run_observation_once_phase30.sh
# Env: KRAKEN_ALPHA_ROOT overrides repo root detection.

set -euo pipefail

if [[ -n "${KRAKEN_ALPHA_ROOT:-}" ]]; then
  REPO_ROOT="$(cd "${KRAKEN_ALPHA_ROOT}" && pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
cd "${REPO_ROOT}"

OBS_BASE="${REPO_ROOT}/reports/paper_observation_phase28"
OPS_LOGS="${OBS_BASE}/ops_logs"
STOP_FLAG="${OBS_BASE}/STOP_OBSERVATION"
TIMESTAMP="$(date -u +%Y%m%d_%H%M%S)"
LOG_FILE="${OPS_LOGS}/${TIMESTAMP}.log"

mkdir -p "${OPS_LOGS}"

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "${LOG_FILE}"
}

warn() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: $*" | tee -a "${LOG_FILE}"
}

if [[ -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.venv/bin/activate"
fi

PYTHON="${PYTHON:-python}"

log "Phase 30 observation once — repo=${REPO_ROOT}"

if [[ -f "${STOP_FLAG}" ]]; then
  log "STOP_OBSERVATION present at ${STOP_FLAG} — skipping daemon (exit 0)"
  exit 0
fi

log "Optional cache refresh (failures are non-fatal)"

if ! ${PYTHON} scripts/build_intraday_cache.py --assets ETH --timeframes 4h >>"${LOG_FILE}" 2>&1; then
  warn "build_intraday_cache.py ETH 4h failed — continuing with existing cache"
fi

if ! ${PYTHON} scripts/build_derivatives_cache_phase26.py --assets ETH >>"${LOG_FILE}" 2>&1; then
  warn "build_derivatives_cache_phase26.py ETH failed — continuing with existing cache"
fi

if ! ${PYTHON} scripts/build_basis_cache_phase27.py --assets ETH >>"${LOG_FILE}" 2>&1; then
  warn "build_basis_cache_phase27.py ETH failed — continuing with existing cache"
fi

log "Running overlay observation daemon (once, cache-only, all targets)"
${PYTHON} scripts/run_overlay_observation_daemon_phase28.py \
  --run-all-targets \
  --mode once \
  --cache-only >>"${LOG_FILE}" 2>&1

log "Generating overlay observation reports"
${PYTHON} scripts/generate_overlay_observation_report_phase28.py \
  --all-targets >>"${LOG_FILE}" 2>&1

log "Aggregating observation metrics (Phase 29)"
${PYTHON} scripts/aggregate_observation_metrics_phase29.py >>"${LOG_FILE}" 2>&1

log "Checking state.json legacy metadata"
LEGACY_WARNINGS="$(
  cd "${REPO_ROOT}"
  ${PYTHON} -c "
import sys
from pathlib import Path
sys.path.insert(0, r'${REPO_ROOT}')
from src.bot.observation_ops_guards import check_all_target_state_warnings
from src.bot.overlay_observation_engine import PHASE28_TARGETS, default_state_dir
base = Path(r'${OBS_BASE}')
dirs = [default_state_dir(base, s, v) for s, v, _ in PHASE28_TARGETS]
for msg in check_all_target_state_warnings(dirs):
    print(msg)
"
)"

if [[ -n "${LEGACY_WARNINGS}" ]]; then
  while IFS= read -r line; do
    [[ -n "${line}" ]] && warn "state legacy: ${line}"
  done <<<"${LEGACY_WARNINGS}"
else
  log "state.json legacy check: OK"
fi

log "Phase 30 observation once complete — log=${LOG_FILE}"
