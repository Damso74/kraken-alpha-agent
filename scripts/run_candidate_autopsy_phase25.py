#!/usr/bin/env python3
"""Phase 25 — ultra-strict autopsy for the single Phase 24 validation_candidate."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase23_common import DEFAULT_CACHE_ROOT, write_json  # noqa: E402
from src.bot.phase25_autopsy import (  # noqa: E402
    CandidateSpec,
    run_full_autopsy,
)

DEFAULT_OUTPUT = REPO_ROOT / "reports" / "phase25_autopsy"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 25 candidate autopsy")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--fast", action="store_true", help="Hermetic subset (tests only)")
    return p.parse_args()


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fields = sorted({k for r in rows for k in r})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    spec = CandidateSpec()
    payload = run_full_autopsy(spec, cache_root=args.cache_root)

    summary = {
        "phase": payload["phase"],
        "candidate_run_id": payload["candidate_run_id"],
        "final_verdict": payload["final_verdict"],
        "paper_candidate_count": payload["paper_candidate_count"],
        "paper_observation_candidate_count": payload["paper_observation_candidate_count"],
        "micro_live": payload["micro_live"],
        "baseline_excess_vs_bh_pct": payload["baseline"]["excess_vs_bh_pct"],
        "tests": {t["test_id"]: t["verdict"] for t in payload["tests"]},
    }

    write_json(args.output_dir / "summary.json", summary)
    write_json(args.output_dir / "full_results.json", payload)

    flat_rows: list[dict] = []
    for t in payload["tests"]:
        flat_rows.append(
            {
                "test_id": t["test_id"],
                "verdict": t["verdict"],
                "summary": t["summary"],
            }
        )
    _write_csv(args.output_dir / "results.csv", flat_rows)

    for t in payload["tests"]:
        tid = t["test_id"]
        write_json(args.output_dir / f"{tid}.json", t)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
