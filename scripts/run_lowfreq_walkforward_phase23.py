#!/usr/bin/env python3
"""Walk-forward for Phase 23 low-freq candidates (strict, cache-only)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase23_common import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    OverlayMode,
    build_phase23_instrument,
    run_buy_and_hold,
    write_json,
    write_matrix_csv,
)
from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.phase23_presets import (
    PHASE23_ASSETS,
    PHASE23_LOWFREQ_STRATEGIES,
    PHASE23_TIMEFRAMES,
    phase23_run_id,
)
from src.bot.phase23_walkforward import classify_phase23_walkforward_verdict
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
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 23 walk-forward low-freq")
    p.add_argument("--assets", nargs="+", default=list(PHASE23_ASSETS))
    p.add_argument("--timeframes", nargs="+", default=list(PHASE23_TIMEFRAMES))
    p.add_argument("--strategies", nargs="+", default=list(PHASE23_LOWFREQ_STRATEGIES))
    p.add_argument("--variants", nargs="+", default=["baseline", "slow"])
    p.add_argument("--overlay", default="off", choices=["off", "vol", "panic", "both"])
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "lowfreq_walkforward_phase23",
    )
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--fast", action="store_true")
    return p.parse_args()


def _run_period(
    candles: list,
    strategy,
    *,
    sym: str,
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
        symbol=sym,
        data_ok=data_ok,
    )
    return metrics_to_dict(result.metrics, result.risk_stats), result.equity_curve


def main() -> int:
    args = _parse_args()
    if args.fast:
        args.assets = ["BTC"]
        args.timeframes = ["1d"]
        args.strategies = ["ema_crossover"]
        args.variants = ["baseline"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    exec_cfg = ExecutionConfig(fee_bps=args.fees_bps, slippage_bps=args.slippage_bps)
    overlay: OverlayMode = args.overlay  # type: ignore[assignment]

    results: dict = {
        "phase": 23,
        "axis": "D_walkforward",
        "overlay": overlay,
        "fee_bps": args.fees_bps,
        "runs": [],
    }
    matrix_rows: list[dict] = []
    window_rows: list[dict] = []

    for asset in args.assets:
        sym = asset.upper()
        for tf in args.timeframes:
            for strategy in args.strategies:
                for variant in args.variants:
                    instrument = build_phase23_instrument(
                        strategy, tf, variant, overlay
                    )
                    warmup = instrument.warmup_bars()
                    candles, summary = load_ohlcv_candles(
                        sym,
                        tf,
                        args.cache_root,
                        cache_only=True,
                        warmup_bars=warmup,
                    )
                    data_ok = summary.status == "available"
                    run_id = phase23_run_id(sym, tf, strategy, variant, overlay)

                    if not data_ok:
                        results["runs"].append(
                            {
                                "run_id": run_id,
                                "asset": sym,
                                "timeframe": tf,
                                "strategy": strategy,
                                "variant": variant,
                                "overlay": overlay,
                                "verdict": "blocked_data",
                                "data_ok": False,
                            }
                        )
                        continue

                    bh_full = run_buy_and_hold(
                        candles,
                        symbol=sym,
                        cash=args.cash,
                        exec_cfg=exec_cfg,
                        timeframe=tf,
                        data_ok=True,
                    )
                    full_metrics, _ = _run_period(
                        candles,
                        instrument,
                        sym=sym,
                        cash=args.cash,
                        exec_cfg=exec_cfg,
                        timeframe=tf,
                        data_ok=True,
                    )
                    plan = create_rolling_windows_for_timeframe(candles, tf)
                    plan_summary = summarize_windows(plan)

                    if plan.status != "ok":
                        from src.bot.walkforward_metrics import classify_walkforward_verdict

                        wf = classify_walkforward_verdict(
                            aggregate_window_metrics([]),
                            {
                                "data_ok": True,
                                "plan_status": plan.status,
                                "blocked_reason": plan.blocked_reason,
                            },
                        )
                        results["runs"].append(
                            {
                                "run_id": run_id,
                                "verdict": wf.verdict,
                                "verdict_reasons": wf.reasons,
                                **plan_summary,
                            }
                        )
                        continue

                    holdout_runs: list[WindowRunMetrics] = []
                    validation_runs: list[WindowRunMetrics] = []
                    total_trades = 0
                    turnover_sum = 0.0

                    for window in plan.windows:
                        for period_name in ("validation", "holdout"):
                            ctx = context_candles_for_period(
                                candles, window, period_name, warmup
                            )
                            metrics_row, _eq = _run_period(
                                ctx,
                                instrument,
                                sym=sym,
                                cash=args.cash,
                                exec_cfg=exec_cfg,
                                timeframe=tf,
                                data_ok=True,
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
                                total_trades += wm.trade_count
                            else:
                                validation_runs.append(wm)
                            window_rows.append(
                                {
                                    "run_id": run_id,
                                    "window_id": window.window_id,
                                    "period": period_name,
                                    "net_return_pct": wm.net_return_pct,
                                    "trade_count": wm.trade_count,
                                }
                            )

                    agg = aggregate_window_metrics(holdout_runs, validation_runs)
                    wf = classify_phase23_walkforward_verdict(
                        agg,
                        {
                            "data_ok": True,
                            "plan_status": plan.status,
                            "bh_max_drawdown_pct": float(
                                bh_full.get("max_drawdown_pct", 0.0)
                            ),
                            "full_max_drawdown_pct": float(
                                full_metrics.get("max_drawdown_pct", agg.max_window_drawdown)
                            ),
                            "total_trade_count": total_trades,
                            "turnover_ratio": turnover_sum,
                            "asset_returns": {sym: agg.mean_net_return},
                        },
                    )
                    row = {
                        "run_id": run_id,
                        "asset": sym,
                        "timeframe": tf,
                        "strategy": strategy,
                        "variant": variant,
                        "overlay": overlay,
                        "verdict": wf.verdict,
                        "verdict_reasons": wf.reasons,
                        "bh_max_drawdown_pct": bh_full.get("max_drawdown_pct"),
                        "bh_return_pct": bh_full.get("total_return_pct"),
                        **aggregate_to_dict(agg),
                    }
                    results["runs"].append(row)
                    matrix_rows.append(
                        {
                            "run_id": run_id,
                            "asset": sym,
                            "timeframe": tf,
                            "strategy": strategy,
                            "variant": variant,
                            "verdict": wf.verdict,
                            "median_net_return": agg.median_net_return,
                            "positive_window_rate": agg.positive_window_rate,
                        }
                    )

    write_json(args.output_dir / "results.json", results)
    write_matrix_csv(args.output_dir / "results_matrix.csv", matrix_rows)
    if window_rows:
        with (args.output_dir / "window_results.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            writer = csv.DictWriter(fh, fieldnames=list(window_rows[0].keys()))
            writer.writeheader()
            writer.writerows(window_rows)

    counts: dict[str, int] = {}
    for r in results["runs"]:
        v = r.get("verdict", "unknown")
        counts[v] = counts.get(v, 0) + 1
    pcwf = counts.get("paper_candidate_walkforward", 0)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "runs": len(results["runs"]),
                "paper_candidate_walkforward": pcwf,
                "verdict_counts": counts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
