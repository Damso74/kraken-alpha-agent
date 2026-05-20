#!/usr/bin/env python3
"""Generate paper daily report from daemon state (Phase 19)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.daily_report import write_daily_report


def main() -> int:
    p = argparse.ArgumentParser(description="Generate paper daily report")
    p.add_argument(
        "--state-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "paper_daemon_state",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "paper_live",
    )
    args = p.parse_args()
    path = write_daily_report(args.state_dir, args.output_dir)
    print(json.dumps({"report": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
