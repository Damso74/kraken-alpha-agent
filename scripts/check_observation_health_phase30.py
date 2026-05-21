#!/usr/bin/env python3
"""Phase 30.4 — run observation healthcheck and write HEALTHCHECK.md + healthcheck.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.observation_healthcheck import (
    run_observation_healthcheck,
    write_healthcheck_outputs,
)

DEFAULT_BASE = REPO_ROOT / "reports" / "paper_observation_phase28"
DEFAULT_SUMMARY = REPO_ROOT / "reports" / "phase29_observation_metrics" / "summary.json"


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 30.4 observation healthcheck")
    p.add_argument("--base", type=Path, default=DEFAULT_BASE, help="Observation base dir")
    p.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    p.add_argument("--alerts", type=Path, default=DEFAULT_BASE / "alerts.json")
    p.add_argument(
        "--max-log-age-hours",
        type=float,
        default=6.0,
        help="Fail cron freshness when latest ops log older than this",
    )
    p.add_argument("--json-output", type=Path, default=DEFAULT_BASE / "healthcheck.json")
    p.add_argument("--md-output", type=Path, default=DEFAULT_BASE / "HEALTHCHECK.md")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as exit code 1 (with --exit-code)",
    )
    p.add_argument(
        "--cron-active",
        action="store_true",
        help="Expect periodic VPS cron (stricter ops log checks)",
    )
    p.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit 2 on fail, 1 on warning if --strict else 0 on warning",
    )
    args = p.parse_args()

    report = run_observation_healthcheck(
        observation_base=args.base,
        summary_path=args.summary,
        alerts_path=args.alerts,
        dashboard_path=args.base / "dashboard.html",
        cron_active=args.cron_active,
        max_log_age_hours=args.max_log_age_hours,
    )
    md_path, json_path = write_healthcheck_outputs(
        report,
        md_path=args.md_output,
        json_path=args.json_output,
    )

    status = str(report.get("status") or "fail")
    summary = report.get("summary") or {}
    print(
        json.dumps(
            {
                "status": status,
                "healthcheck_md": str(md_path),
                "healthcheck_json": str(json_path),
                "fail_count": summary.get("fail_count"),
                "warning_count": summary.get("warning_count"),
            },
            indent=2,
        )
    )

    if not args.exit_code:
        return 0
    if status == "fail":
        return 2
    if status == "warning" and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
