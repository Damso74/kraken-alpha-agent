#!/usr/bin/env python3
"""Phase 30.4 — generate OPS_DIGEST.md + ops_digest.json (dry-run notifications)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.observation_ops_digest import build_ops_digest, write_ops_digest_outputs

DEFAULT_BASE = REPO_ROOT / "reports" / "paper_observation_phase28"
DEFAULT_SUMMARY = REPO_ROOT / "reports" / "phase29_observation_metrics" / "summary.json"


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 30.4 observation ops digest")
    p.add_argument("--base", type=Path, default=DEFAULT_BASE)
    p.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    p.add_argument("--alerts", type=Path, default=DEFAULT_BASE / "alerts.json")
    p.add_argument("--healthcheck", type=Path, default=DEFAULT_BASE / "healthcheck.json")
    p.add_argument("--md-out", type=Path, default=DEFAULT_BASE / "OPS_DIGEST.md")
    p.add_argument("--json-out", type=Path, default=DEFAULT_BASE / "ops_digest.json")
    args = p.parse_args()

    digest = build_ops_digest(
        observation_base=args.base,
        summary_path=args.summary,
        alerts_path=args.alerts,
        health_path=args.healthcheck,
    )
    md_path, json_path = write_ops_digest_outputs(
        digest,
        md_path=args.md_out,
        json_path=args.json_out,
    )
    print(
        json.dumps(
            {
                "ops_digest_md": str(md_path),
                "ops_digest_json": str(json_path),
                "status": digest.get("status"),
                "next_action": digest.get("next_action"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
