#!/usr/bin/env python3
"""Phase 24 walk-forward holdout sensitivity (cache-only, full history when data_ok)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase23_common import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    build_phase23_instrument,
    run_buy_and_hold,
    write_json,
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
    PHASE23_VARIANTS,
    phase23_run_id,
)
from src.bot.phase24_walkforward import (
    HOLDOUT_PCT_VARIANTS,
    classify_phase24_sensitivity_verdict,
    count_holdout_beats_bh,
    create_holdout_sensitivity_plan,
)
from src.bot.portfolio import PaperPortfolio
from src.bot.regime_router import BuyAndHoldStrategy
from src.bot.risk_manager import RiskManager
from src.bot.walkforward import context_candles_for_period, summarize_windows
from src.bot.walkforward_metrics import (
    WindowRunMetrics,
    aggregate_to_dict,
    aggregate_window_metrics,
)

DEFAULT_OUTPUT = REPO_ROOT / "reports" / "phase24_walkforward_sensitivity"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 24 WF holdout sensitivity")
    p.add_argument("--assets", nargs="+", default=list(PHASE23_ASSETS))
    p.add_argument("--timeframes", nargs="+", default=list(PHASE23_TIMEFRAMES))
    p.add_argument("--strategies", nargs="+", default=list(PHASE23_LOWFREQ_STRATEGIES))
    p.add_argument("--variants", nargs="+", default=list(PHASE23_VARIANTS))
    p.add_argument("--overlay", default="off", choices=["off", "vol", "panic", "both"])
    p.add_argument(
        "--holdout-pcts",
        nargs="+",
        type=float,
        default=list(HOLDOUT_PCT_VARIANTS),
    )
    p.add_argument(
        "--window-modes",
        nargs="+",
        default=["rolling", "expanding"],
        choices=["rolling", "expanding"],
    )
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
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
) -> tuple[dict, list[float], object]:
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
    turnover = 0.0
    if result.metrics.starting_equity > 1e-12 and result.metrics.trade_count > 0:
        traded = sum(
            abs(float(t.get("quantity", 0)) * float(t.get("price", 0)))
            for t in journal.trades
        )
        turnover = traded / result.metrics.starting_equity
    metrics = metrics_to_dict(result.metrics, result.risk_stats)
    metrics["turnover_ratio"] = round(turnover, 4)
    return metrics, result.equity_curve, journal


def _bh_holdout_return(
    candles: list,
    window,
    *,
    sym: str,
    cash: float,
    exec_cfg: ExecutionConfig,
    timeframe: str,
) -> float:
    ctx = context_candles_for_period(candles, window, "holdout", warmup_bars=1)
    bh, _, _ = _run_period(
        ctx,
        BuyAndHoldStrategy(),
        sym=sym,
        cash=cash,
        exec_cfg=exec_cfg,
        timeframe=timeframe,
        data_ok=True,
    )
    return float(bh.get("total_return_pct", 0.0))


def main() -> int:
    args = _parse_args()
    if args.fast:
        args.assets = ["BTC"]
        args.timeframes = ["1d"]
        args.strategies = ["ema_crossover"]
        args.variants = ["baseline"]
        args.holdout_pcts = [0.20]
        args.window_modes = ["rolling"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    exec_cfg = ExecutionConfig(fee_bps=args.fees_bps, slippage_bps=args.slippage_bps)

    result_rows: list[dict] = []
    by_asset_strategy: dict[tuple[str, str, str], list[dict]] = {}

    for asset in args.assets:
        sym = asset.upper()
        for tf in args.timeframes:
            for strategy in args.strategies:
                for variant in args.variants:
                    instrument = build_phase23_instrument(
                        strategy, tf, variant, args.overlay
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
                    base_id = phase23_run_id(sym, tf, strategy, variant, args.overlay)

                    if not data_ok:
                        for holdout_pct in args.holdout_pcts:
                            for mode in args.window_modes:
                                result_rows.append(
                                    {
                                        "run_id": f"{base_id}_h{int(holdout_pct*100)}_{mode}",
                                        "asset": sym,
                                        "timeframe": tf,
                                        "strategy": strategy,
                                        "variant": variant,
                                        "overlay": args.overlay,
                                        "holdout_pct": holdout_pct,
                                        "window_mode": mode,
                                        "bars": 0,
                                        "verdict": "blocked_data",
                                        "reason": summary.blocked_reason,
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
                    full_metrics, _, _ = _run_period(
                        candles,
                        instrument,
                        sym=sym,
                        cash=args.cash,
                        exec_cfg=exec_cfg,
                        timeframe=tf,
                        data_ok=True,
                    )

                    for holdout_pct in args.holdout_pcts:
                        for window_mode in args.window_modes:
                            run_id = f"{base_id}_h{int(holdout_pct * 100)}_{window_mode}"
                            plan = create_holdout_sensitivity_plan(
                                candles,
                                tf,
                                holdout_pct,
                                window_mode=window_mode,
                            )
                            plan_summary = summarize_windows(plan)

                            if plan.status != "ok":
                                result_rows.append(
                                    {
                                        "run_id": run_id,
                                        "asset": sym,
                                        "timeframe": tf,
                                        "strategy": strategy,
                                        "variant": variant,
                                        "overlay": args.overlay,
                                        "holdout_pct": holdout_pct,
                                        "window_mode": window_mode,
                                        "bars": len(candles),
                                        "verdict": "insufficient_candles",
                                        "reason": plan.blocked_reason,
                                        **plan_summary,
                                    }
                                )
                                continue

                            holdout_runs: list[WindowRunMetrics] = []
                            validation_runs: list[WindowRunMetrics] = []
                            bh_holdout_returns: list[float] = []
                            total_trades = 0
                            turnover_vals: list[float] = []

                            for window in plan.windows:
                                bh_ret = _bh_holdout_return(
                                    candles,
                                    window,
                                    sym=sym,
                                    cash=args.cash,
                                    exec_cfg=exec_cfg,
                                    timeframe=tf,
                                )
                                bh_holdout_returns.append(bh_ret)

                                for period_name in ("validation", "holdout"):
                                    ctx = context_candles_for_period(
                                        candles, window, period_name, warmup
                                    )
                                    metrics_row, _, journal = _run_period(
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
                                        net_return_pct=float(
                                            metrics_row["total_return_pct"]
                                        ),
                                        max_drawdown_pct=float(
                                            metrics_row["max_drawdown_pct"]
                                        ),
                                        trade_count=int(metrics_row["trade_count"]),
                                        cost_drag_pct=float(
                                            metrics_row.get("cost_drag_pct", 0.0)
                                        ),
                                        sharpe_ratio=float(
                                            metrics_row.get("sharpe_ratio", 0.0)
                                        ),
                                    )
                                    if period_name == "holdout":
                                        wm.passed = (
                                            wm.net_return_pct > bh_ret
                                            and wm.trade_count
                                            >= 1
                                        )
                                        holdout_runs.append(wm)
                                        total_trades += wm.trade_count
                                        turnover_vals.append(
                                            float(metrics_row.get("turnover_ratio", 0))
                                        )
                                    else:
                                        validation_runs.append(wm)

                            agg = aggregate_window_metrics(holdout_runs, validation_runs)
                            bh_beats, median_excess = count_holdout_beats_bh(
                                holdout_runs, bh_holdout_returns
                            )
                            bh_return = float(bh_full.get("total_return_pct", 0.0))
                            strat_return = float(
                                full_metrics.get("total_return_pct", 0.0)
                            )
                            wf = classify_phase24_sensitivity_verdict(
                                agg,
                                {
                                    "data_ok": True,
                                    "plan_status": plan.status,
                                    "bh_max_drawdown_pct": float(
                                        bh_full.get("max_drawdown_pct", 0.0)
                                    ),
                                    "full_max_drawdown_pct": float(
                                        full_metrics.get(
                                            "max_drawdown_pct",
                                            agg.max_window_drawdown,
                                        )
                                    ),
                                    "total_trade_count": total_trades,
                                    "turnover_ratio": mean(turnover_vals)
                                    if turnover_vals
                                    else 0.0,
                                    "holdout_beats_bh_count": bh_beats,
                                    "holdout_bh_windows": len(bh_holdout_returns),
                                    "median_excess_vs_bh_pct": median_excess,
                                    "full_excess_vs_bh_pct": strat_return - bh_return,
                                    "overlay_only_outperformance": args.overlay != "off",
                                },
                            )

                            row = {
                                "run_id": run_id,
                                "asset": sym,
                                "timeframe": tf,
                                "strategy": strategy,
                                "variant": variant,
                                "overlay": args.overlay,
                                "holdout_pct": holdout_pct,
                                "window_mode": window_mode,
                                "bars": len(candles),
                                "train_bars": plan.train_bars,
                                "validation_bars": plan.validation_bars,
                                "holdout_bars": plan.holdout_bars,
                                "windows_total": len(plan.windows),
                                "total_return_pct": strat_return,
                                "bh_return_pct": bh_return,
                                "excess_vs_bh_pct": round(strat_return - bh_return, 4),
                                "max_drawdown_pct": full_metrics.get("max_drawdown_pct"),
                                "bh_max_drawdown_pct": bh_full.get("max_drawdown_pct"),
                                "sharpe_ratio": full_metrics.get("sharpe_ratio"),
                                "trade_count": full_metrics.get("trade_count"),
                                "win_rate_pct": full_metrics.get("win_rate_pct"),
                                "turnover_ratio": full_metrics.get("turnover_ratio"),
                                "fee_bps": args.fees_bps,
                                "holdout_beats_bh": bh_beats,
                                "median_excess_vs_bh_pct": median_excess,
                                "verdict": wf.verdict,
                                "reason": "; ".join(wf.reasons),
                                **aggregate_to_dict(agg),
                            }
                            result_rows.append(row)
                            key = (sym, strategy, tf)
                            by_asset_strategy.setdefault(key, []).append(row)

    validation_candidates = [
        r for r in result_rows if r.get("verdict") == "validation_candidate"
    ]
    unstable = [
        r
        for r in result_rows
        if r.get("verdict") in ("unstable", "weak", "failed_walkforward")
    ]
    paper_count = sum(
        1
        for r in result_rows
        if r.get("verdict") in ("paper_candidate", "paper_candidate_walkforward")
    )

    by_as_tf_rows: list[dict] = []
    for (sym, strategy, tf), rows in sorted(by_asset_strategy.items()):
        verdicts = [r.get("verdict") for r in rows]
        by_as_tf_rows.append(
            {
                "asset": sym,
                "strategy": strategy,
                "timeframe": tf,
                "runs": len(rows),
                "validation_candidate": sum(
                    1 for v in verdicts if v == "validation_candidate"
                ),
                "best_excess_vs_bh": max(
                    (float(r.get("excess_vs_bh_pct", -999)) for r in rows),
                    default=0.0,
                ),
                "verdicts": ",".join(sorted(set(verdicts))),
            }
        )

    summary = {
        "phase": 24,
        "axis": "walkforward_holdout_sensitivity",
        "overlay": args.overlay,
        "fee_bps": args.fees_bps,
        "runs_total": len(result_rows),
        "validation_candidate_count": len(validation_candidates),
        "paper_candidate_count": paper_count,
        "unstable_count": len(unstable),
        "holdout_pcts": args.holdout_pcts,
        "window_modes": args.window_modes,
    }

    write_json(args.output_dir / "summary.json", summary)
    write_json(
        args.output_dir / "validation_candidates.json",
        {"candidates": validation_candidates},
    )

    def _write_csv(path: Path, rows: list[dict]) -> None:
        if not rows:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = sorted({k for r in rows for k in r})
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    _write_csv(args.output_dir / "results.csv", result_rows)
    _write_csv(args.output_dir / "by_asset_strategy_tf.csv", by_as_tf_rows)
    _write_csv(args.output_dir / "unstable_cases.csv", unstable)
    _write_csv(args.output_dir / "validation_candidates.csv", validation_candidates)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
