#!/usr/bin/env python3
"""Phase 22 — timeframe × turnover analysis from Phase 21 + cache runs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase22_common import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    PHASE21_TOURNAMENT,
    load_json_runs,
    resolve_grid,
    run_backtest_cell,
    strategy_family,
    write_matrix_csv,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 22 timeframe turnover analysis")
    p.add_argument(
        "--input",
        type=Path,
        default=PHASE21_TOURNAMENT / "results.json",
        help="Phase 21 tournament results (fallback if missing turnover)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "timeframe_turnover_phase22",
    )
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument(
        "--refresh-turnover",
        action="store_true",
        help="Re-run baseline backtests to compute turnover_ratio",
    )
    p.add_argument("--fast", action="store_true", help="BTC only for refresh")
    return p.parse_args()


def _aggregate_by_timeframe(rows: list[dict]) -> dict[str, dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("timeframe", "1d"))].append(row)

    out: dict[str, dict] = {}
    for tf, items in sorted(buckets.items()):
        returns = [float(r.get("total_return_pct", 0)) for r in items]
        trades = [int(r.get("trade_count", 0)) for r in items]
        costs = [float(r.get("cost_drag_pct", 0)) for r in items]
        turnover = [float(r.get("turnover_ratio", 0)) for r in items]
        verdicts = [str(r.get("verdict", "")) for r in items]
        out[tf] = {
            "runs": len(items),
            "median_return_pct": median(returns) if returns else 0.0,
            "median_trades": median(trades) if trades else 0,
            "median_cost_drag_pct": median(costs) if costs else 0.0,
            "median_turnover_ratio": median(turnover) if turnover else 0.0,
            "paper_candidate_count": sum(1 for v in verdicts if v == "paper_candidate"),
            "blocked_costs_count": sum(1 for v in verdicts if v == "blocked_costs"),
            "blocked_risk_count": sum(1 for v in verdicts if v == "blocked_risk"),
            "insufficient_trades_count": sum(1 for v in verdicts if v == "insufficient_trades"),
        }
    return out


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_json_runs(args.input)
    if args.refresh_turnover or not rows or "turnover_ratio" not in rows[0]:
        assets = ["BTC"] if args.fast else ["BTC", "ETH", "SOL"]
        timeframes = ["1d"] if args.fast else ["1d", "4h", "1h"]
        grid = resolve_grid(assets, timeframes)
        rows = [
            run_backtest_cell(a, tf, s, fees_bps=40.0, slippage_bps=5.0, cache_root=args.cache_root)
            for a, tf, s in grid
        ]

    by_tf = _aggregate_by_timeframe(rows)
    by_family_tf: dict[str, dict[str, dict]] = defaultdict(dict)
    fam_buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        fam = strategy_family(str(row.get("strategy", "")))
        tf = str(row.get("timeframe", "1d"))
        fam_buckets[(fam, tf)].append(row)
    for (fam, tf), items in fam_buckets.items():
        by_family_tf[fam][tf] = {
            "median_trades": median([int(r.get("trade_count", 0)) for r in items]),
            "median_return_pct": median([float(r.get("total_return_pct", 0)) for r in items]),
            "median_cost_drag_pct": median([float(r.get("cost_drag_pct", 0)) for r in items]),
        }

    summary = {
        "source": str(args.input),
        "by_timeframe": by_tf,
        "by_family_timeframe": {k: v for k, v in by_family_tf.items()},
        "interpretation": {
            "1d": "Low turnover, often insufficient_trades — signals too sparse",
            "4h": "Higher activity; mix of blocked_risk and blocked_costs",
            "1h": "Highest turnover; cost drag dominates, negative median returns",
        },
    }

    (args.output_dir / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_matrix_csv(args.output_dir / "runs.csv", rows)

    md = ["# Timeframe × turnover — Phase 22", ""]
    for tf, stats in by_tf.items():
        md.append(f"## {tf}")
        md.append(f"- Median trades: {stats['median_trades']:.1f}")
        md.append(f"- Median return: {stats['median_return_pct']:.2f}%")
        md.append(f"- Median cost drag: {stats['median_cost_drag_pct']:.1f}%")
        md.append(f"- Paper candidates: {stats['paper_candidate_count']}")
        md.append("")
    (args.output_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"output_dir": str(args.output_dir), "timeframes": list(by_tf)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
