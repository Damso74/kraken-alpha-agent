"""Shared Phase 27 helpers (cache-only tournaments + autopsy)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts._phase23_common import (
    DEFAULT_CACHE_ROOT,
    run_phase23_cell,
)
from src.bot.basis_crowding_overlay import (
    BasisCrowdingOverlayStrategy,
    classify_phase27_tournament_verdict,
    compare_overlay_modes,
    load_basis_overlay_inputs,
)
from src.bot.crowding_overlay import compare_baseline_vs_overlay
from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.phase23_presets import build_phase23_strategy
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_adjusted_metrics import compute_risk_adjusted_bundle
from src.bot.risk_manager import RiskManager

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_overlay_metrics(
    candles: list,
    inner_strategy: str,
    variant: str,
    timeframe: str,
    sym: str,
    *,
    mode: str,
    f_rows: list,
    b_rows: list,
    fees_bps: float,
    slippage_bps: float,
    cash: float,
) -> dict[str, Any]:
    inner = build_phase23_strategy(inner_strategy, timeframe, variant)
    overlay_inst = BasisCrowdingOverlayStrategy(inner, timeframe, mode=mode)  # type: ignore[arg-type]
    overlay_inst.bind_derivatives(candles, f_rows, b_rows if mode == "funding_basis" else [])
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
    ra = compute_risk_adjusted_bundle(
        equity_curve=result.equity_curve,
        strategy_return_pct=result.metrics.total_return_pct,
        strategy_max_dd_pct=result.metrics.max_drawdown_pct,
        bh_return_pct=0.0,
        bh_max_dd_pct=0.0,
        journal=journal,
        warmup_bars=warmup,
        total_bars=len(candles),
    )
    return {
        "data_ok": True,
        "total_return_pct": result.metrics.total_return_pct,
        "max_drawdown_pct": result.metrics.max_drawdown_pct,
        "trade_count": result.metrics.trade_count,
        "sharpe_ratio": result.metrics.sharpe_ratio,
        **ra,
    }


def run_basis_overlay_cell(
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

    f_rows, b_rows, deriv_status = load_basis_overlay_inputs(sym, timeframe, cache_root)
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
            "basis_overlay": "blocked_data",
            "verdict": "blocked_data",
            "blocked_reason": "funding cache missing",
        }

    funding_only = _run_overlay_metrics(
        candles,
        strategy,
        variant,
        timeframe,
        sym,
        mode="funding_only",
        f_rows=f_rows,
        b_rows=[],
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        cash=cash,
    )

    if deriv_status == "funding_only" or not b_rows:
        cmp = compare_baseline_vs_overlay(baseline, funding_only)
        verdict = classify_phase27_tournament_verdict(
            baseline,
            funding_only,
            funding_only,
        )
        return {
            "asset": sym,
            "timeframe": timeframe,
            "strategy": strategy,
            "variant": variant,
            "data_ok": True,
            "baseline_return_pct": baseline.get("total_return_pct"),
            "funding_only_return_pct": funding_only.get("total_return_pct"),
            "funding_basis_return_pct": None,
            "baseline_max_dd_pct": baseline.get("max_drawdown_pct"),
            "funding_only_max_dd_pct": funding_only.get("max_drawdown_pct"),
            "funding_basis_max_dd_pct": None,
            "compare_funding_only": cmp,
            "best_mode": "funding_only" if cmp.get("improved_risk_only") or cmp.get("improved_alpha") else "baseline",
            "basis_status": "blocked_data",
            "verdict": verdict,
        }

    funding_basis = _run_overlay_metrics(
        candles,
        strategy,
        variant,
        timeframe,
        sym,
        mode="funding_basis",
        f_rows=f_rows,
        b_rows=b_rows,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        cash=cash,
    )
    cmp_modes = compare_overlay_modes(baseline, funding_only, funding_basis)
    verdict = classify_phase27_tournament_verdict(baseline, funding_only, funding_basis)

    return {
        "asset": sym,
        "timeframe": timeframe,
        "strategy": strategy,
        "variant": variant,
        "data_ok": True,
        "baseline_return_pct": baseline.get("total_return_pct"),
        "funding_only_return_pct": funding_only.get("total_return_pct"),
        "funding_basis_return_pct": funding_basis.get("total_return_pct"),
        "baseline_max_dd_pct": baseline.get("max_drawdown_pct"),
        "funding_only_max_dd_pct": funding_only.get("max_drawdown_pct"),
        "funding_basis_max_dd_pct": funding_basis.get("max_drawdown_pct"),
        "compare_modes": cmp_modes,
        "best_mode": cmp_modes.get("best_mode"),
        "basis_status": "available",
        "verdict": verdict,
    }
