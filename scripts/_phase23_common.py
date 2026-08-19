"""Shared Phase 23 factory / walk-forward helpers (cache-only)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Literal

from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.phase23_presets import build_phase23_strategy, phase23_run_id
from src.bot.portfolio import PaperPortfolio
from src.bot.regime_overlay import RegimeOverlayStrategy
from src.bot.regime_router import BuyAndHoldStrategy
from src.bot.risk_adjusted_metrics import compute_risk_adjusted_bundle
from src.bot.risk_manager import RiskManager
from src.strategies.volatility_targeting import wrap_with_vol_targeting

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_ROOT = REPO_ROOT / "data" / "collector_cache"

OverlayMode = Literal["off", "vol", "panic", "both"]

OVERLAY_MODES: tuple[OverlayMode, ...] = ("off", "vol", "panic", "both")


def cap_candles(candles: list, max_bars: int) -> list:
    if max_bars <= 0 or len(candles) <= max_bars:
        return candles
    return candles[-max_bars:]


def apply_overlay(
    strategy: object,
    timeframe: str,
    overlay: OverlayMode,
    *,
    regime_precomputed: list | None = None,
) -> object:
    if overlay == "off":
        return strategy
    base = strategy
    if overlay in ("vol", "both"):
        base = wrap_with_vol_targeting(base, timeframe)
    if overlay in ("panic", "both"):
        base = RegimeOverlayStrategy(
            base,
            timeframe,
            precomputed_features=regime_precomputed,
            cache_regime_features=regime_precomputed is None,
        )
    return base


def build_phase23_instrument(
    strategy: str,
    timeframe: str,
    variant: str,
    overlay: OverlayMode,
    *,
    regime_precomputed: list | None = None,
):
    inner = build_phase23_strategy(strategy, timeframe, variant)
    return apply_overlay(
        inner, timeframe, overlay, regime_precomputed=regime_precomputed
    )


def run_buy_and_hold(
    candles: list[dict],
    *,
    symbol: str,
    cash: float,
    exec_cfg: ExecutionConfig,
    timeframe: str,
    data_ok: bool,
) -> dict[str, Any]:
    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    result = run_paper_backtest(
        candles,
        BuyAndHoldStrategy(),
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": timeframe, "use_classify_verdict": False},
        symbol=symbol,
        data_ok=data_ok,
    )
    return metrics_to_dict(result.metrics, result.risk_stats)


def run_phase23_cell(
    asset: str,
    timeframe: str,
    strategy: str,
    variant: str,
    overlay: OverlayMode,
    *,
    fees_bps: float = 40.0,
    slippage_bps: float = 5.0,
    cash: float = 1000.0,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    candles: list[dict] | None = None,
    data_ok: bool | None = None,
    candle_count: int | None = None,
    bh_metrics: dict[str, Any] | None = None,
    regime_precomputed: list | None = None,
) -> dict[str, Any]:
    sym = asset.upper()
    instrument = build_phase23_instrument(
        strategy, timeframe, variant, overlay, regime_precomputed=regime_precomputed
    )
    warmup = instrument.warmup_bars()
    if candles is None:
        candles, summary = load_ohlcv_candles(
            sym,
            timeframe,
            cache_root,
            cache_only=True,
            warmup_bars=warmup,
        )
        data_ok = summary.status == "available"
        candle_count = summary.candle_count

    exec_cfg = ExecutionConfig(fee_bps=fees_bps, slippage_bps=slippage_bps)
    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    result = run_paper_backtest(
        candles or [],
        instrument,
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": timeframe, "use_classify_verdict": False},
        symbol=sym,
        data_ok=bool(data_ok),
    )
    if bh_metrics is None and candles:
        bh_metrics = run_buy_and_hold(
            candles,
            symbol=sym,
            cash=cash,
            exec_cfg=exec_cfg,
            timeframe=timeframe,
            data_ok=bool(data_ok),
        )

    turnover = 0.0
    if result.metrics.starting_equity > 1e-12 and result.metrics.trade_count > 0:
        traded = sum(
            abs(float(t.get("quantity", 0)) * float(t.get("price", 0)))
            for t in (journal.trades if journal else [])
        )
        turnover = traded / result.metrics.starting_equity

    ra = compute_risk_adjusted_bundle(
        equity_curve=result.equity_curve,
        strategy_return_pct=result.metrics.total_return_pct,
        strategy_max_dd_pct=result.metrics.max_drawdown_pct,
        bh_return_pct=float(bh_metrics.get("total_return_pct", 0.0) if bh_metrics else 0.0),
        bh_max_dd_pct=float(bh_metrics.get("max_drawdown_pct", 0.0) if bh_metrics else 0.0),
        journal=journal,
        warmup_bars=warmup,
        total_bars=len(candles or []),
    )

    return {
        "run_id": phase23_run_id(sym, timeframe, strategy, variant, overlay),
        "asset": sym,
        "timeframe": timeframe,
        "strategy": strategy,
        "variant": variant,
        "overlay": overlay,
        "data_ok": bool(data_ok),
        "candle_count": candle_count or len(candles or []),
        "total_return_pct": result.metrics.total_return_pct,
        "max_drawdown_pct": result.metrics.max_drawdown_pct,
        "trade_count": result.metrics.trade_count,
        "sharpe_ratio": result.metrics.sharpe_ratio,
        "cost_drag_pct": result.metrics.cost_drag_pct,
        "turnover_ratio": round(turnover, 4),
        "fee_bps": fees_bps,
        **ra,
    }


def write_matrix_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
