#!/usr/bin/env python3
"""Phase 27B — basis + funding overlay tournament (cache-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase23_common import DEFAULT_CACHE_ROOT, write_json, write_matrix_csv  # noqa: E402
from scripts._phase27_common import run_basis_overlay_cell  # noqa: E402
from src.bot.phase26_walkforward import (
    PHASE26_ASSETS,
    PHASE26_OVERLAY_STRATEGIES,
)

DEFAULT_OUT = REPO_ROOT / "reports" / "phase27_basis_overlay"


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 27 basis overlay tournament")
    p.add_argument("--assets", nargs="+", default=list(PHASE26_ASSETS))
    p.add_argument("--timeframes", nargs="+", default=["4h"])
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument(
        "--fast",
        action="store_true",
        help="BTC 4h trend_following slow only",
    )
    args = p.parse_args()

    combos = (
        [("BTC", "4h", "trend_following", "slow")]
        if args.fast
        else [
            (a, tf, s, v)
            for a in args.assets
            for tf in args.timeframes
            for s, v in PHASE26_OVERLAY_STRATEGIES
        ]
    )

    rows: list[dict] = []
    for asset, tf, strategy, variant in combos:
        row = run_basis_overlay_cell(
            asset, tf, strategy, variant, cache_root=args.cache_root
        )
        rows.append(row)
        print(f"{asset} {tf} {strategy}/{variant} -> {row.get('verdict')} best={row.get('best_mode')}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_matrix_csv(args.output_dir / "results_matrix.csv", rows)
    summary = {
        "runs_total": len(rows),
        "overlay_only": sum(1 for r in rows if r.get("verdict") == "overlay_only"),
        "weak": sum(1 for r in rows if r.get("verdict") == "weak"),
        "kill": sum(1 for r in rows if r.get("verdict") == "kill"),
        "blocked_data": sum(1 for r in rows if r.get("verdict") == "blocked_data"),
        "validation_candidate": 0,
        "funding_basis_best": sum(1 for r in rows if r.get("best_mode") == "funding_basis"),
        "funding_only_best": sum(1 for r in rows if r.get("best_mode") == "funding_only"),
    }
    write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
