"""Shared Phase 26 helpers (cache-only tournaments)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts._phase23_common import (
    DEFAULT_CACHE_ROOT,
    run_buy_and_hold,
    run_phase23_cell,
    write_json,
    write_matrix_csv,
)
from src.bot.crowding_overlay import (
    CrowdingOverlayStrategy,
    compare_baseline_vs_overlay,
    load_derivatives_for_asset,
)
from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.phase23_presets import build_phase23_strategy
from src.bot.phase26_walkforward import classify_phase26_overlay_verdict
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_adjusted_metrics import compute_risk_adjusted_bundle
from src.bot.risk_manager import RiskManager

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_crowding_overlay_cell(
    asset: str,
    timeframe: str,
    strategy: str,
    variant: str,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    fees_bps: float = 40.0,
    slippage_bps: float = 5.0,
    cash: float = 1000.0,
) -> dict[str, Any]:
    sym = asset.upper()
    candles, summary = load_ohlcv_candles(sym, timeframe, cache_root, cache_only=True)
    if summary.status != "available":
        return {
            "asset": sym,
            "timeframe": timeframe,
            "strategy": strategy,
            "variant": variant,
            "data_ok": False,
            "verdict": "blocked_data",
            "blocked_reason": summary.blocked_reason,
        }

    f_rows, o_rows, deriv_status = load_derivatives_for_asset(sym, timeframe, cache_root)
    baseline = run_phase23_cell(
        sym,
        timeframe,
        strategy,
        variant,
        "off",
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        cash=cash,
        cache_root=cache_root,
        candles=candles,
        data_ok=True,
        candle_count=len(candles),
    )

    if deriv_status == "blocked_data":
        return {
            **baseline,
            "crowding_overlay": "blocked_data",
            "verdict": "blocked_data",
            "blocked_reason": "derivatives cache missing",
        }

    inner = build_phase23_strategy(strategy, timeframe, variant)
    overlay_inst = CrowdingOverlayStrategy(inner, timeframe)
    overlay_inst.bind_derivatives(candles, f_rows, o_rows)
    warmup = overlay_inst.warmup_bars()
    exec_cfg = ExecutionConfig(fee_bps=fees_bps, slippage_bps=slippage_bps)
    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    result = run_paper_backtest(
        candles,
        overlay_inst,
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": timeframe, "use_classify_verdict": False},
        symbol=sym,
        data_ok=True,
    )
    bh = run_buy_and_hold(
        candles,
        symbol=sym,
        cash=cash,
        exec_cfg=exec_cfg,
        timeframe=timeframe,
        data_ok=True,
    )
    ra = compute_risk_adjusted_bundle(
        equity_curve=result.equity_curve,
        strategy_return_pct=result.metrics.total_return_pct,
        strategy_max_dd_pct=result.metrics.max_drawdown_pct,
        bh_return_pct=float(bh.get("total_return_pct", 0)),
        bh_max_dd_pct=float(bh.get("max_drawdown_pct", 0)),
        journal=journal,
        warmup_bars=warmup,
        total_bars=len(candles),
    )
    overlay_metrics = {
        "data_ok": True,
        "total_return_pct": result.metrics.total_return_pct,
        "max_drawdown_pct": result.metrics.max_drawdown_pct,
        "trade_count": result.metrics.trade_count,
        "sharpe_ratio": result.metrics.sharpe_ratio,
        **ra,
    }
    cmp = compare_baseline_vs_overlay(baseline, overlay_metrics)
    verdict = classify_phase26_overlay_verdict(baseline, overlay_metrics)

    return {
        "asset": sym,
        "timeframe": timeframe,
        "strategy": strategy,
        "variant": variant,
        "data_ok": True,
        "baseline_return_pct": baseline.get("total_return_pct"),
        "overlay_return_pct": overlay_metrics.get("total_return_pct"),
        "baseline_max_dd_pct": baseline.get("max_drawdown_pct"),
        "overlay_max_dd_pct": overlay_metrics.get("max_drawdown_pct"),
        "baseline_excess_vs_bh_pct": baseline.get("excess_vs_bh_pct"),
        "overlay_excess_vs_bh_pct": overlay_metrics.get("excess_vs_bh_pct"),
        "compare": cmp,
        "verdict": verdict,
        "crowding_overlay": "on",
    }
