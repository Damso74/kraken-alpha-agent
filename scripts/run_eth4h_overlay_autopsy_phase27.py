#!/usr/bin/env python3
"""Phase 27D — ETH 4h crowding overlay autopsy (Phase 26 overlay_only targets)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase23_common import DEFAULT_CACHE_ROOT, write_json, write_matrix_csv  # noqa: E402
from src.bot.crowding_overlay import load_derivatives_for_asset  # noqa: E402
from src.bot.data_loader import load_ohlcv_candles  # noqa: E402
from src.bot.phase27_eth4h_autopsy import (  # noqa: E402
    ETH4H_AUTOPSY_TARGETS,
    run_eth4h_autopsy_cell,
)

DEFAULT_OUT = REPO_ROOT / "reports" / "phase27_eth4h_overlay_autopsy"


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 27 ETH 4h overlay autopsy")
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--fee-bps", type=float, default=40.0)
    args = p.parse_args()

    sym = "ETH"
    tf = "4h"
    candles, summary = load_ohlcv_candles(sym, tf, args.cache_root, cache_only=True)
    if summary.status != "available":
        print(f"blocked_data: {summary.blocked_reason}")
        return 1

    f_rows, o_rows, deriv_status = load_derivatives_for_asset(sym, tf, args.cache_root)
    if deriv_status == "blocked_data":
        print("derivatives cache missing — autopsy blocked")
        return 1

    rows: list[dict] = []
    for strategy, variant in ETH4H_AUTOPSY_TARGETS:
        row = run_eth4h_autopsy_cell(
            strategy,
            variant,
            candles,
            sym=sym,
            timeframe=tf,
            f_rows=f_rows,
            o_rows=o_rows,
            fee_bps=args.fee_bps,
        )
        rows.append(row)
        print(f"ETH 4h {strategy}/{variant} -> {row.get('verdict')}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_matrix_csv(args.output_dir / "results_matrix.csv", rows)
    summary_out = {
        "targets": len(rows),
        "useful_overlay": sum(1 for r in rows if r.get("verdict") == "useful_overlay"),
        "decorative": sum(1 for r in rows if r.get("verdict") == "decorative"),
        "kill_overlay": sum(1 for r in rows if r.get("verdict") == "kill_overlay"),
        "validation_candidate": 0,
    }
    write_json(args.output_dir / "summary.json", summary_out)
    print(json.dumps(summary_out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
