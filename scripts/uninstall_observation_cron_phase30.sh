#!/usr/bin/env bash
# Phase 30.4 — remove observation cron line(s) for this repo.
# Usage: bash scripts/uninstall_observation_cron_phase30.sh

set -euo pipefail

if [[ -n "${KRAKEN_ALPHA_ROOT:-}" ]]; then
  REPO_ROOT="$(cd "${KRAKEN_ALPHA_ROOT}" && pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

OPS_SCRIPT="${REPO_ROOT}/scripts/ops_run_observation_once_phase30.sh"
MARKER="# kraken-alpha-agent observation cron phase30"

EXISTING="$(crontab -l 2>/dev/null || true)"
if [[ -z "${EXISTING}" ]]; then
  echo "No crontab — nothing to remove."
  exit 0
fi

if ! echo "${EXISTING}" | grep -Fq "${OPS_SCRIPT}"; then
  echo "No cron line referencing ${OPS_SCRIPT}."
  exit 0
fi

NEW_CRON="$(echo "${EXISTING}" | grep -Fv "${OPS_SCRIPT}" | grep -Fv "${MARKER}" || true)"
if [[ -n "${NEW_CRON}" ]]; then
  echo "${NEW_CRON}" | crontab -
else
  crontab -r 2>/dev/null || true
fi

echo "Removed observation cron for ${REPO_ROOT}."
