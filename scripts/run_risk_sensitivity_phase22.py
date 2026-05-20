#!/usr/bin/env python3
"""Phase 22 — risk manager sensitivity grid (diagnostic only, cache-only)."""

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
    PHASE21_TOURNAMENT,
    load_candle_bundle,
    load_json_runs,
    resolve_grid,
    run_backtest_cell,
    write_matrix_csv,
)
from scripts.run_strategy_tournament import PHASE16_STRATEGY_NAMES, _instantiate_strategy  # noqa: E402
from src.bot.metrics import MAX_RISK_DENIAL_RATE  # noqa: E402
from src.bot.risk_manager import RiskConfig  # noqa: E402

POSITION_GRID = (0.10, 0.25, 0.50)
DRAWDOWN_GRID = (0.10, 0.15, 0.25)
VERDICT_DENIAL_THRESHOLDS = (0.20, 0.30, 0.50)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 22 risk manager sensitivity (cache-only)")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL"])
    p.add_argument("--timeframes", nargs="+", default=["1d", "4h", "1h"])
    p.add_argument("--strategies", nargs="+", default=None)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "risk_sensitivity_phase22",
    )
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument(
        "--baseline-results",
        type=Path,
        default=PHASE21_TOURNAMENT / "results.json",
        help="Phase 21 tournament for comparison",
    )
    p.add_argument(
        "--fast",
        action="store_true",
        help="BTC 1d, 2 strategies, reduced risk grid",
    )
    return p.parse_args()


def _build_summary(runs: list[dict], baseline_runs: list[dict]) -> dict:
    baseline_by_id = {
        (r["asset"], r["timeframe"], r["strategy"]): r for r in baseline_runs
    }

    improved_to_paper: list[str] = []
    still_blocked: list[str] = []
    over_constrained_signals = 0

    for (asset, tf, strat), base in baseline_by_id.items():
        base_verdict = base.get("verdict", "")
        base_denial = float(base.get("risk_denial_rate", 0))
        if base_verdict != "blocked_risk" and base_denial <= MAX_RISK_DENIAL_RATE:
            continue
        over_constrained_signals += 1
        rel_runs = [
            r
            for r in runs
            if r["asset"] == asset
            and r["timeframe"] == tf
            and r["strategy"] == strat
            and r.get("max_position_fraction") == 0.50
            and r.get("max_drawdown_pct_config") == 0.25
        ]
        if not rel_runs:
            continue
        best = max(rel_runs, key=lambda r: float(r["total_return_pct"]))
        if best["verdict"] == "paper_candidate":
            improved_to_paper.append(f"{asset}_{tf}_{strat}")
        else:
            still_blocked.append(f"{asset}_{tf}_{strat}")

    denial_analysis: dict[str, int] = defaultdict(int)
    for row in runs:
        rate = float(row.get("risk_denial_rate", 0))
        if rate > 0.50:
            denial_analysis["denial_gt_50pct"] += 1
        elif rate > MAX_RISK_DENIAL_RATE:
            denial_analysis["denial_gt_verdict_threshold_30pct"] += 1
        elif rate > 0.10:
            denial_analysis["denial_10_30pct"] += 1
        else:
            denial_analysis["denial_lte_10pct"] += 1

    return {
        "risk_config_grid": {
            "max_position_fraction": list(POSITION_GRID),
            "max_drawdown_pct": list(DRAWDOWN_GRID),
        },
        "verdict_classifier_note": {
            "MAX_RISK_DENIAL_RATE": MAX_RISK_DENIAL_RATE,
            "threshold_sweep_for_diagnosis": list(VERDICT_DENIAL_THRESHOLDS),
            "note": "RiskManager has no denial-rate param; threshold is verdict-only in metrics.py",
        },
        "baseline_blocked_risk_or_high_denial": over_constrained_signals,
        "relaxed_config_paper_candidates": improved_to_paper,
        "relaxed_config_still_blocked": still_blocked,
        "denial_rate_distribution": dict(denial_analysis),
        "over_constrained_hypothesis": (
            "partial"
            if improved_to_paper and len(improved_to_paper) < over_constrained_signals // 2
            else "unlikely"
            if not improved_to_paper
            else "likely"
        ),
    }


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pos_grid = POSITION_GRID
    dd_grid = DRAWDOWN_GRID
    assets = list(args.assets)
    timeframes = list(args.timeframes)
    strategies = args.strategies
    if args.fast:
        assets = ["BTC"]
        timeframes = ["1d"]
        strategies = ["trend_following", "grid"]
        pos_grid = (0.25, 0.50)
        dd_grid = (0.15, 0.25)

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

    for max_pos in pos_grid:
        for max_dd in dd_grid:
            cfg = RiskConfig(max_position_fraction=max_pos, max_drawdown_pct=max_dd)
            for asset, tf, strat in grid:
                candles, data_ok, candle_count = bundles[(asset, tf)]
                row = run_backtest_cell(
                    asset,
                    tf,
                    strat,
                    fees_bps=40.0,
                    slippage_bps=5.0,
                    cache_root=args.cache_root,
                    risk_config=cfg,
                    candles=candles,
                    data_ok=data_ok,
                    candle_count=candle_count,
                )
                row["risk_grid_key"] = f"pos{max_pos}_dd{max_dd}"
                runs.append(row)

    baseline_runs = load_json_runs(args.baseline_results)
    summary = _build_summary(runs, baseline_runs)
    payload = {
        "phase": 22,
        "axis": "risk_sensitivity",
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

    md = [
        "# Risk sensitivity — Phase 22",
        "",
        f"- Grid: max_position_fraction={list(pos_grid)}, max_drawdown_pct={list(dd_grid)}",
        f"- Baseline blocked/high-denial cells: {summary['baseline_blocked_risk_or_high_denial']}",
        f"- Over-constrained hypothesis: **{summary['over_constrained_hypothesis']}**",
        f"- Paper candidates under relaxed config: {len(summary['relaxed_config_paper_candidates'])}",
        "",
        "## Denial rate distribution (all grid runs)",
        "",
    ]
    for k, v in summary["denial_rate_distribution"].items():
        md.append(f"- {k}: {v}")
    (args.output_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"output_dir": str(args.output_dir), "runs": len(runs)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
