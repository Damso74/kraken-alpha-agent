#!/usr/bin/env python3
"""Generate Phase 28 overlay observation daily/weekly reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.daily_report import (
    write_overlay_observation_report,
    write_weekly_overlay_report,
)
from src.bot.overlay_observation_engine import PHASE28_TARGETS, default_state_dir

DEFAULT_BASE = REPO_ROOT / "reports" / "paper_observation_phase28"


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 28 overlay observation report")
    p.add_argument("--state-dir", type=Path, default=None)
    p.add_argument("--state-base", type=Path, default=DEFAULT_BASE)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_BASE)
    p.add_argument("--weekly", action="store_true", default=False)
    p.add_argument("--all-targets", action="store_true", default=False)
    args = p.parse_args()

    if args.weekly or args.all_targets:
        dirs = [
            default_state_dir(args.state_base, s, v)
            for s, v, _ in PHASE28_TARGETS
        ]
        path = write_weekly_overlay_report(dirs, args.output_dir)
        print(json.dumps({"weekly_report": str(path)}, indent=2))
        return 0

    state_dir = args.state_dir or default_state_dir(
        args.state_base, "trend_following", "baseline"
    )
    path = write_overlay_observation_report(state_dir, args.output_dir)
    print(json.dumps({"report": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
