#!/usr/bin/env python3
"""Phase 26D — walk-forward on crowding overlay candidates (cache-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase23_common import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    build_phase23_instrument,
    run_buy_and_hold,
    write_json,
    write_matrix_csv,
)
from scripts._phase26_common import run_crowding_overlay_cell  # noqa: E402
from src.bot.crowding_overlay import CrowdingOverlayStrategy, load_derivatives_for_asset
from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.phase23_presets import build_phase23_strategy
from src.bot.phase24_walkforward import (
    HOLDOUT_PCT_VARIANTS,
    classify_phase24_sensitivity_verdict,
    count_holdout_beats_bh,
    create_holdout_sensitivity_plan,
)
from src.bot.phase26_walkforward import (
    PHASE26_OVERLAY_STRATEGIES,
    classify_phase26_overlay_verdict,
    summarize_phase26_walkforward,
)
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_manager import RiskManager
from src.bot.walkforward import context_candles_for_period
from src.bot.walkforward_metrics import WindowRunMetrics, aggregate_window_metrics

DEFAULT_OUT = REPO_ROOT / "reports" / "phase26_walkforward"
EVENT_SUMMARY = REPO_ROOT / "reports" / "phase26_event_studies" / "summary.json"


def _load_event_gate() -> bool:
    if not EVENT_SUMMARY.is_file():
        return True
    data = json.loads(EVENT_SUMMARY.read_text(encoding="utf-8"))
    for b in data.get("bundles", []):
        if b.get("proceed_to_overlay"):
            return True
    return False


def _run_period(candles, strategy, *, sym, cash, exec_cfg, timeframe, data_ok):
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
    return metrics_to_dict(result.metrics, result.risk_stats), journal


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 26 crowding walk-forward")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH"])
    p.add_argument("--timeframes", nargs="+", default=["4h"])
    p.add_argument("--holdout-pct", type=float, default=0.30)
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--skip-event-gate", action="store_true")
    p.add_argument("--fast", action="store_true")
    args = p.parse_args()

    if not args.skip_event_gate and not _load_event_gate():
        write_json(
            args.output_dir / "summary.json",
            {"skipped": True, "reason": "event_study_no_non_trivial_signal"},
        )
        print("skipped: event study gate failed")
        return 0

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

    exec_cfg = ExecutionConfig(fee_bps=40.0, slippage_bps=5.0)
    rows: list[dict] = []

    for asset, tf, strategy, variant in combos:
        sym = asset.upper()
        candles, summary = load_ohlcv_candles(sym, tf, args.cache_root, cache_only=True)
        f_rows, o_rows, deriv_status = load_derivatives_for_asset(sym, tf, args.cache_root)
        if summary.status != "available" or deriv_status == "blocked_data":
            rows.append(
                {
                    "asset": sym,
                    "timeframe": tf,
                    "strategy": strategy,
                    "variant": variant,
                    "verdict": "blocked_data",
                    "data_ok": False,
                }
            )
            continue

        inner = build_phase23_strategy(strategy, tf, variant)
        overlay_inst = CrowdingOverlayStrategy(inner, tf)
        overlay_inst.bind_derivatives(candles, f_rows, o_rows)

        plan = create_holdout_sensitivity_plan(candles, tf, args.holdout_pct)
        if plan.status != "ok":
            cell = run_crowding_overlay_cell(
                sym, tf, strategy, variant, cache_root=args.cache_root
            )
            cell["wf_skipped"] = plan.blocked_reason
            rows.append(cell)
            continue

        holdout_runs: list[WindowRunMetrics] = []
        bh_returns: list[float] = []
        for w in plan.windows:
            for period in ("validation", "holdout"):
                ctx = context_candles_for_period(
                    candles, w, period, warmup_bars=overlay_inst.warmup_bars()
                )
                if len(ctx) < 30:
                    continue
                m, _ = _run_period(
                    ctx,
                    overlay_inst,
                    sym=sym,
                    cash=1000.0,
                    exec_cfg=exec_cfg,
                    timeframe=tf,
                    data_ok=True,
                )
                if period == "holdout":
                    bh_ctx = context_candles_for_period(candles, w, "holdout", warmup_bars=1)
                    bh_m = run_buy_and_hold(
                        bh_ctx,
                        symbol=sym,
                        cash=1000.0,
                        exec_cfg=exec_cfg,
                        timeframe=tf,
                        data_ok=True,
                    )
                    bh_returns.append(float(bh_m.get("total_return_pct", 0)))
                    holdout_runs.append(
                        WindowRunMetrics(
                            window_id=w.window_id,
                            period=period,
                            net_return_pct=float(m.get("total_return_pct", 0)),
                            max_drawdown_pct=float(m.get("max_drawdown_pct", 0)),
                            trade_count=int(m.get("trade_count", 0)),
                            sharpe_ratio=float(m.get("sharpe_ratio", 0)),
                        )
                    )

        agg = aggregate_window_metrics(holdout_runs, [])
        total_trades = sum(wm.trade_count for wm in holdout_runs)
        beats, median_ex = count_holdout_beats_bh(holdout_runs, bh_returns)
        wf = classify_phase24_sensitivity_verdict(
            agg,
            {
                "holdout_beats_bh_count": beats,
                "holdout_bh_windows": len(bh_returns),
                "total_trade_count": total_trades,
                "overlay_only_outperformance": True,
            },
        )
        cell = run_crowding_overlay_cell(
            sym, tf, strategy, variant, cache_root=args.cache_root
        )
        cell["wf_verdict"] = wf.verdict
        cell["holdout_beats_bh"] = beats
        cell["verdict"] = classify_phase26_overlay_verdict(
            {"data_ok": True, "total_return_pct": cell.get("baseline_return_pct", 0),
             "max_drawdown_pct": cell.get("baseline_max_dd_pct", 0)},
            {"data_ok": True, "total_return_pct": cell.get("overlay_return_pct", 0),
             "max_drawdown_pct": cell.get("overlay_max_dd_pct", 0)},
            wf_verdict=wf.verdict,
        )
        rows.append(cell)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_matrix_csv(args.output_dir / "results.csv", rows)
    summary = summarize_phase26_walkforward(rows)
    summary["holdout_pct"] = args.holdout_pct
    write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
