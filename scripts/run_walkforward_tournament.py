#!/usr/bin/env python3
"""Walk-forward strategy tournament (Phase 17, cache-only, no live trading)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_strategy_tournament import (  # noqa: E402
    PHASE16_STRATEGY_NAMES,
    _instantiate_strategy,
)
from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_manager import RiskManager
from src.bot.walkforward import (
    context_candles_for_period,
    create_rolling_windows_for_timeframe,
    summarize_windows,
)
from src.bot.walkforward_metrics import (
    WindowRunMetrics,
    aggregate_to_dict,
    aggregate_window_metrics,
    classify_walkforward_verdict,
)

ALL_STRATEGIES = PHASE16_STRATEGY_NAMES


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Walk-forward paper tournament (cache-only)")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH"])
    p.add_argument("--timeframes", nargs="+", default=["1d", "4h", "1h"], choices=["1d", "4h", "1h"])
    p.add_argument(
        "--strategies",
        nargs="+",
        default=["all"],
        help="Strategy names or 'all' for Phase 16 zoo",
    )
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "walkforward_phase17",
    )
    p.add_argument("--cache-only", action="store_true", default=True)
    p.add_argument(
        "--cache-root",
        type=Path,
        default=REPO_ROOT / "data" / "collector_cache",
    )
    p.add_argument("--vol-targeting", choices=["off", "on"], default="off")
    return p.parse_args()


def _resolve_strategies(raw: list[str]) -> tuple[str, ...]:
    if len(raw) == 1 and raw[0].lower() == "all":
        return ALL_STRATEGIES
    return tuple(raw)


def _run_period_backtest(
    candles: list[dict],
    strategy,
    *,
    symbol: str,
    cash: float,
    exec_cfg: ExecutionConfig,
    timeframe: str,
    data_ok: bool,
) -> tuple[dict, list[float]]:
    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    result = run_paper_backtest(
        candles,
        strategy,
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": timeframe, "use_classify_verdict": False},
        symbol=symbol,
        data_ok=data_ok,
    )
    row = metrics_to_dict(result.metrics, result.risk_stats)
    return row, result.equity_curve


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    strategy_names = _resolve_strategies(args.strategies)
    vol_on = args.vol_targeting == "on"
    exec_cfg = ExecutionConfig(fee_bps=args.fees_bps, slippage_bps=args.slippage_bps)

    results: dict = {
        "phase": 17,
        "timeframes": list(args.timeframes),
        "strategies": list(strategy_names),
        "cash": args.cash,
        "fee_bps": args.fees_bps,
        "slippage_bps": args.slippage_bps,
        "cache_only": bool(args.cache_only),
        "vol_targeting": args.vol_targeting,
        "runs": [],
    }
    window_rows: list[dict] = []
    equity_rows: list[dict] = []
    matrix_rows: list[dict] = []

    for asset in args.assets:
        sym = asset.upper()
        for tf in args.timeframes:
            warmup = 0
            for strat_name in strategy_names:
                s = _instantiate_strategy(strat_name, tf, vol_targeting=vol_on)
                warmup = max(warmup, s.warmup_bars())

            candles, summary = load_ohlcv_candles(
                sym,
                tf,
                args.cache_root,
                cache_only=args.cache_only,
                warmup_bars=warmup,
            )
            data_ok = summary.status == "available"

            if not data_ok:
                for strat_name in strategy_names:
                    run_id = f"{sym}_{tf}_{strat_name}"
                    wf_verdict = classify_walkforward_verdict(
                        aggregate_window_metrics([]),
                        {
                            "data_ok": False,
                            "blocked_reason": summary.blocked_reason or "cache missing",
                        },
                    )
                    row = {
                        "run_id": run_id,
                        "asset": sym,
                        "timeframe": tf,
                        "strategy": strat_name,
                        "verdict": wf_verdict.verdict,
                        "verdict_reasons": wf_verdict.reasons,
                        "data_ok": False,
                        "cache_status": summary.status,
                        "cache_path": summary.path,
                    }
                    results["runs"].append(row)
                    matrix_rows.append(
                        {
                            "asset": sym,
                            "timeframe": tf,
                            "strategy": strat_name,
                            "verdict": wf_verdict.verdict,
                            "windows_total": 0,
                            "holdout_pass_rate": 0.0,
                        }
                    )
                continue

            plan = create_rolling_windows_for_timeframe(candles, tf)
            plan_summary = summarize_windows(plan)

            for strat_name in strategy_names:
                strategy = _instantiate_strategy(strat_name, tf, vol_targeting=vol_on)
                run_id = f"{sym}_{tf}_{strat_name}"
                holdout_runs: list[WindowRunMetrics] = []
                validation_runs: list[WindowRunMetrics] = []

                if plan.status != "ok":
                    wf_verdict = classify_walkforward_verdict(
                        aggregate_window_metrics([]),
                        {
                            "data_ok": True,
                            "plan_status": plan.status,
                            "blocked_reason": plan.blocked_reason,
                        },
                    )
                    row = {
                        "run_id": run_id,
                        "asset": sym,
                        "timeframe": tf,
                        "strategy": strat_name,
                        "verdict": wf_verdict.verdict,
                        "verdict_reasons": wf_verdict.reasons,
                        "data_ok": True,
                        "plan_status": plan.status,
                        "candle_count": summary.candle_count,
                        **plan_summary,
                    }
                    results["runs"].append(row)
                    matrix_rows.append(
                        {
                            "asset": sym,
                            "timeframe": tf,
                            "strategy": strat_name,
                            "verdict": wf_verdict.verdict,
                            "windows_total": 0,
                            "holdout_pass_rate": 0.0,
                        }
                    )
                    continue

                for window in plan.windows:
                    for period_name in ("validation", "holdout"):
                        ctx = context_candles_for_period(
                            candles, window, period_name, strategy.warmup_bars()
                        )
                        metrics_row, eq = _run_period_backtest(
                            ctx,
                            strategy,
                            symbol=sym,
                            cash=args.cash,
                            exec_cfg=exec_cfg,
                            timeframe=tf,
                            data_ok=data_ok,
                        )
                        wm = WindowRunMetrics(
                            window_id=window.window_id,
                            period=period_name,
                            net_return_pct=float(metrics_row["total_return_pct"]),
                            max_drawdown_pct=float(metrics_row["max_drawdown_pct"]),
                            trade_count=int(metrics_row["trade_count"]),
                            cost_drag_pct=float(metrics_row["cost_drag_pct"]),
                            sharpe_ratio=float(metrics_row["sharpe_ratio"]),
                        )
                        if period_name == "holdout":
                            wm.passed = (
                                wm.net_return_pct >= -5.0
                                and wm.max_drawdown_pct <= 20.0
                                and wm.trade_count >= 1
                            )
                            holdout_runs.append(wm)
                        else:
                            validation_runs.append(wm)

                        window_rows.append(
                            {
                                "run_id": run_id,
                                "asset": sym,
                                "timeframe": tf,
                                "strategy": strat_name,
                                "window_id": window.window_id,
                                "period": period_name,
                                "net_return_pct": wm.net_return_pct,
                                "max_drawdown_pct": wm.max_drawdown_pct,
                                "trade_count": wm.trade_count,
                                "cost_drag_pct": wm.cost_drag_pct,
                                "passed": wm.passed,
                            }
                        )
                        if period_name == "holdout" and eq:
                            for i, e in enumerate(eq[-20:]):
                                equity_rows.append(
                                    {
                                        "run_id": run_id,
                                        "window_id": window.window_id,
                                        "bar_offset": i,
                                        "equity": e,
                                    }
                                )

                agg = aggregate_window_metrics(holdout_runs, validation_runs)
                wf_verdict = classify_walkforward_verdict(
                    agg,
                    {"data_ok": True, "plan_status": plan.status},
                )
                row = {
                    "run_id": run_id,
                    "asset": sym,
                    "timeframe": tf,
                    "strategy": strat_name,
                    "verdict": wf_verdict.verdict,
                    "verdict_reasons": wf_verdict.reasons,
                    "data_ok": True,
                    "plan_status": plan.status,
                    "candle_count": summary.candle_count,
                    **plan_summary,
                    **aggregate_to_dict(agg),
                }
                results["runs"].append(row)
                matrix_rows.append(
                    {
                        "asset": sym,
                        "timeframe": tf,
                        "strategy": strat_name,
                        "verdict": wf_verdict.verdict,
                        "windows_total": agg.windows_total,
                        "holdout_pass_rate": agg.holdout_pass_rate,
                        "median_net_return": agg.median_net_return,
                    }
                )

    (args.output_dir / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    if window_rows:
        with (args.output_dir / "window_results.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            writer = csv.DictWriter(fh, fieldnames=list(window_rows[0].keys()))
            writer.writeheader()
            writer.writerows(window_rows)
    if matrix_rows:
        with (args.output_dir / "results_matrix.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            writer = csv.DictWriter(fh, fieldnames=list(matrix_rows[0].keys()))
            writer.writeheader()
            writer.writerows(matrix_rows)
    if equity_rows:
        with (args.output_dir / "equity_by_window.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["run_id", "window_id", "bar_offset", "equity"],
            )
            writer.writeheader()
            writer.writerows(equity_rows)

    verdict_counts: dict[str, int] = {}
    for r in results["runs"]:
        v = r["verdict"]
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "runs": len(results["runs"]),
                "verdict_counts": verdict_counts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
