#!/usr/bin/env bash
# Phase 30.4 — install VPS observation cron (4h) without duplicate lines.
# Usage: bash scripts/install_observation_cron_phase30.sh
# Env: KRAKEN_ALPHA_ROOT (default: parent of scripts/)

set -euo pipefail

if [[ -n "${KRAKEN_ALPHA_ROOT:-}" ]]; then
  REPO_ROOT="$(cd "${KRAKEN_ALPHA_ROOT}" && pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

OPS_BASE="${REPO_ROOT}/reports/paper_observation_phase28"
OPS_LOGS="${OPS_BASE}/ops_logs"
CRON_STDOUT="${OPS_LOGS}/cron_stdout.log"
OPS_SCRIPT="${REPO_ROOT}/scripts/ops_run_observation_once_phase30.sh"

mkdir -p "${OPS_LOGS}"

CRON_LINE="0 */4 * * * KRAKEN_ALPHA_ROOT=${REPO_ROOT} /bin/bash ${OPS_SCRIPT} >> ${CRON_STDOUT} 2>&1"
MARKER="# kraken-alpha-agent observation cron phase30"

EXISTING="$(crontab -l 2>/dev/null || true)"
if echo "${EXISTING}" | grep -Fq "${OPS_SCRIPT}"; then
  echo "Cron already installed for ${OPS_SCRIPT} — no change."
  exit 0
fi

{
  echo "${EXISTING}"
  echo ""
  echo "${MARKER}"
  echo "${CRON_LINE}"
} | crontab -

echo "Installed observation cron (every 4h UTC)."
echo "  Repo: ${REPO_ROOT}"
echo "  Log:  ${CRON_STDOUT}"
echo "  Line: ${CRON_LINE}"
