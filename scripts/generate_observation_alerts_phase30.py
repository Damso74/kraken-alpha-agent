#!/usr/bin/env python3
"""Phase 30.3 — generate observation ops alerts (ALERTS.md + alerts.json)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.observation_alerts import (
    collect_observation_alerts,
    write_alert_outputs,
)

DEFAULT_BASE = REPO_ROOT / "reports" / "paper_observation_phase28"
DEFAULT_SUMMARY = REPO_ROOT / "reports" / "phase29_observation_metrics" / "summary.json"


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 30.3 observation alerts")
    p.add_argument("--observation-base", type=Path, default=DEFAULT_BASE)
    p.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    p.add_argument("--md-out", type=Path, default=DEFAULT_BASE / "ALERTS.md")
    p.add_argument("--json-out", type=Path, default=DEFAULT_BASE / "alerts.json")
    p.add_argument(
        "--fail-on-report-error",
        action="store_true",
        default=False,
        help="Simulate report_generation_failed alert (testing)",
    )
    args = p.parse_args()

    report = collect_observation_alerts(
        observation_base=args.observation_base,
        summary_path=args.summary,
        report_generation_failed=args.fail_on_report_error,
    )
    md_path, json_path = write_alert_outputs(
        report,
        md_path=args.md_out,
        json_path=args.json_out,
    )
    print(
        json.dumps(
            {
                "alerts_md": str(md_path),
                "alerts_json": str(json_path),
                "critical_count": report.critical_count,
                "warning_count": report.warning_count,
                "exit_code_recommended": report.exit_code_recommended,
            },
            indent=2,
        )
    )
    return report.exit_code_recommended


if __name__ == "__main__":
    raise SystemExit(main())
