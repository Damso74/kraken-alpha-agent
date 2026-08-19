#!/usr/bin/env python3
"""Phase 22 — fee & slippage sensitivity grid (cache-only, diagnostic)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase22_common import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    fee_interpretation,
    load_candle_bundle,
    resolve_grid,
    run_backtest_cell,
    write_matrix_csv,
)
from scripts.run_strategy_tournament import (  # noqa: E402
    PHASE16_STRATEGY_NAMES,
    _instantiate_strategy,
)

FEE_GRID = (0.0, 10.0, 25.0, 40.0)
SLIPPAGE_GRID = (0.0, 5.0, 10.0)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 22 fee/slippage sensitivity (cache-only)")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL"])
    p.add_argument("--timeframes", nargs="+", default=["1d", "4h", "1h"])
    p.add_argument(
        "--strategies",
        nargs="+",
        default=None,
        help="Default: full Phase 16 zoo; use subset for --fast",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "fee_sensitivity_phase22",
    )
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument(
        "--fast",
        action="store_true",
        help="BTC 1d only, 3 strategies (smoke / CI)",
    )
    return p.parse_args()


def _build_summary(runs: list[dict]) -> dict:
    by_cell: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in runs:
        key = (row["asset"], row["timeframe"], row["strategy"])
        by_cell[key].append(row)

    interpretations: list[dict] = []
    for key, items in sorted(by_cell.items()):
        by_fee = {(r["fee_bps"], r["slippage_bps"]): r for r in items}
        zero = by_fee.get((0.0, 0.0))
        baseline = by_fee.get((40.0, 5.0))
        moderate = by_fee.get((10.0, 5.0))
        high = by_fee.get((40.0, 10.0))
        if not zero or not baseline:
            continue
        label = fee_interpretation(
            float(zero["total_return_pct"]),
            float(baseline["total_return_pct"]),
            float(high["total_return_pct"]) if high else float(baseline["total_return_pct"]),
        )
        interpretations.append(
            {
                "asset": key[0],
                "timeframe": key[1],
                "strategy": key[2],
                "interpretation": label,
                "return_at_0bps": zero["total_return_pct"],
                "return_at_40_5bps": baseline["total_return_pct"],
                "return_at_10_5bps": moderate["total_return_pct"] if moderate else None,
                "trade_count_baseline": baseline["trade_count"],
            }
        )

    counts = defaultdict(int)
    for item in interpretations:
        counts[item["interpretation"]] += 1

    return {
        "grid": {"fees_bps": list(FEE_GRID), "slippage_bps": list(SLIPPAGE_GRID)},
        "interpretation_counts": dict(counts),
        "interpretation_guide": {
            "no_edge_at_zero_fees": "Loses even at 0 bps — no raw edge",
            "killed_by_costs": "Positive at 0 bps but dies at 40 bps — turnover/cost drag",
            "cost_sensitive_survives_moderate": "Survives 10-25 bps band — low-freq candidate",
            "positive_across_grid": "Positive across tested grid (rare; verify trades)",
        },
        "per_strategy": interpretations,
    }


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    strategies = args.strategies
    assets = list(args.assets)
    timeframes = list(args.timeframes)
    if args.fast:
        assets = ["BTC"]
        timeframes = ["1d"]
        strategies = ["trend_following", "breakout", "grid"]

    strats = tuple(strategies or PHASE16_STRATEGY_NAMES)
    grid = resolve_grid(assets, timeframes, strats)
    runs: list[dict] = []

    bundles: dict[tuple[str, str], tuple[list[dict], bool, int]] = {}
    for asset, tf, _ in grid:
        key = (asset, tf)
        if key not in bundles:
            warmup = max(
                _instantiate_strategy(s, tf, vol_targeting=False).warmup_bars() for s in strats
            )
            bundles[key] = load_candle_bundle(asset, tf, args.cache_root, warmup_bars=warmup)

    for fee_bps in FEE_GRID:
        for slip_bps in SLIPPAGE_GRID:
            for asset, tf, strat in grid:
                candles, data_ok, candle_count = bundles[(asset, tf)]
                row = run_backtest_cell(
                    asset,
                    tf,
                    strat,
                    fees_bps=fee_bps,
                    slippage_bps=slip_bps,
                    cache_root=args.cache_root,
                    candles=candles,
                    data_ok=data_ok,
                    candle_count=candle_count,
                )
                row["grid_key"] = f"fee{int(fee_bps)}_slip{int(slip_bps)}"
                runs.append(row)

    summary = _build_summary(runs)
    payload = {
        "phase": 22,
        "axis": "fee_sensitivity",
        "cache_only": True,
        "fast_mode": args.fast,
        "runs": runs,
        "summary": summary,
    }
    (args.output_dir / "results.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    write_matrix_csv(args.output_dir / "matrix.csv", runs)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    md_lines = [
        "# Fee sensitivity — Phase 22",
        "",
        f"- Grid: fees_bps={list(FEE_GRID)}, slippage_bps={list(SLIPPAGE_GRID)}",
        f"- Runs: {len(runs)}",
        "",
        "## Interpretation counts",
        "",
    ]
    for k, v in sorted(summary["interpretation_counts"].items()):
        md_lines.append(f"- **{k}**: {v}")
    md_lines.extend(["", "## Guide", ""])
    for k, v in summary["interpretation_guide"].items():
        md_lines.append(f"- `{k}`: {v}")
    (args.output_dir / "summary.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(json.dumps({"output_dir": str(args.output_dir), "runs": len(runs)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
