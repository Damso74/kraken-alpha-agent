"""Shared helpers for Phase 22 performance diagnosis (cache-only, no live)."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.run_strategy_tournament import PHASE16_STRATEGY_NAMES, _instantiate_strategy
from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import classify_strategy_verdict
from src.bot.paper_engine import run_paper_backtest
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_manager import RiskConfig, RiskManager

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_ROOT = REPO_ROOT / "data" / "collector_cache"
PHASE21_TOURNAMENT = REPO_ROOT / "reports" / "strategy_tournament_phase21_rerun"
PHASE21_WALKFORWARD = REPO_ROOT / "reports" / "walkforward_phase21_rerun"

STRATEGY_FAMILIES: dict[str, tuple[str, ...]] = {
    "trend_ema_donchian": ("trend_following", "ema_crossover", "donchian_breakout"),
    "breakout_atr": ("breakout", "atr_breakout"),
    "rsi_bollinger_mr": ("mean_reversion", "rsi_mean_reversion", "bollinger_mean_reversion"),
    "grid": ("grid",),
    "vol_targeting": (),  # overlay; tournament runs vol_targeting=off in phase21
    "regime_router": ("regime_router",),
}

FAMILY_LABELS = {
    "trend_ema_donchian": "Trend / EMA / Donchian",
    "breakout_atr": "Breakout / ATR",
    "rsi_bollinger_mr": "RSI / Bollinger / MR",
    "grid": "Grid",
    "vol_targeting": "Vol targeting (overlay)",
    "regime_router": "Regime router",
}


def strategy_family(strategy: str) -> str:
    if strategy == "regime_router":
        return "regime_router"
    for family, names in STRATEGY_FAMILIES.items():
        if strategy in names:
            return family
    return "other"


def load_candle_bundle(
    asset: str,
    timeframe: str,
    cache_root: Path,
    *,
    warmup_bars: int = 0,
) -> tuple[list[dict], bool, int]:
    candles, summary = load_ohlcv_candles(
        asset.upper(),
        timeframe,
        cache_root,
        cache_only=True,
        warmup_bars=warmup_bars,
    )
    ok = summary.status == "available"
    return candles, ok, summary.candle_count


def resolve_grid(
    assets: Sequence[str],
    timeframes: Sequence[str],
    strategies: Sequence[str] | None = None,
) -> list[tuple[str, str, str]]:
    strats = tuple(strategies or PHASE16_STRATEGY_NAMES)
    return [(a.upper(), tf, s) for a in assets for tf in timeframes for s in strats]


def run_backtest_cell(
    asset: str,
    timeframe: str,
    strategy_name: str,
    *,
    fees_bps: float,
    slippage_bps: float,
    cash: float = 1000.0,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    risk_config: RiskConfig | None = None,
    vol_targeting: bool = False,
    candles: list[dict] | None = None,
    data_ok: bool | None = None,
    candle_count: int | None = None,
) -> dict[str, Any]:
    sym = asset.upper()
    strategy = _instantiate_strategy(strategy_name, timeframe, vol_targeting=vol_targeting)
    warmup = strategy.warmup_bars()
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
    else:
        _ = data_ok

    exec_cfg = ExecutionConfig(fee_bps=fees_bps, slippage_bps=slippage_bps)
    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    result = run_paper_backtest(
        candles or [],
        strategy,
        portfolio,
        RiskManager(risk_config),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": timeframe},
        symbol=sym,
        data_ok=bool(data_ok),
    )
    ctx = {
        "timeframe": timeframe,
        "data_ok": bool(data_ok),
        "risk_stats": result.risk_stats,
        "candle_count": candle_count or len(candles or []),
        "usable_bars": max(0, (candle_count or len(candles or [])) - strategy.warmup_bars()),
        "blocked_reason": "missing cache" if not data_ok else "",
        "enforce_candle_minimum": bool(data_ok),
    }
    verdict = classify_strategy_verdict(result.metrics, ctx)
    turnover = 0.0
    if result.metrics.starting_equity > 1e-12 and result.metrics.trade_count > 0:
        traded_notional = sum(
            abs(float(t.get("quantity", 0)) * float(t.get("price", 0)))
            for t in (journal.trades if journal else [])
        )
        turnover = traded_notional / result.metrics.starting_equity

    row = {
        "asset": sym,
        "timeframe": timeframe,
        "strategy": strategy_name,
        "strategy_family": strategy_family(strategy_name),
        "verdict": verdict.verdict,
        "verdict_reasons": verdict.reasons,
        "data_ok": data_ok,
        "total_return_pct": result.metrics.total_return_pct,
        "trade_count": result.metrics.trade_count,
        "cost_drag_pct": result.metrics.cost_drag_pct,
        "fees_usd": result.metrics.fees_usd,
        "slippage_drag_usd": result.metrics.slippage_drag_usd,
        "max_drawdown_pct": result.metrics.max_drawdown_pct,
        "sharpe_ratio": result.metrics.sharpe_ratio,
        "risk_denial_rate": round(result.risk_stats.risk_denial_rate, 4),
        "risk_denials_count": result.risk_stats.risk_denials_count,
        "risk_rules_triggered": result.risk_stats.risk_rules_triggered,
        "stopped_by_risk": result.risk_stats.stopped_by_risk,
        "turnover_ratio": round(turnover, 4),
        "fee_bps": fees_bps,
        "slippage_bps": slippage_bps,
        **(
            {
                "max_position_fraction": risk_config.max_position_fraction,
                "max_drawdown_pct_config": risk_config.max_drawdown_pct,
            }
            if risk_config
            else {}
        ),
    }
    return row


def load_json_runs(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("runs", []))


def write_matrix_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fee_interpretation(
    zero_fee_return: float,
    baseline_return: float,
    high_fee_return: float,
) -> str:
    if zero_fee_return <= 0:
        return "no_edge_at_zero_fees"
    if baseline_return <= 0 <= zero_fee_return:
        return "cost_sensitive_survives_moderate"
    if high_fee_return <= 0 < zero_fee_return:
        return "killed_by_costs"
    return "positive_across_grid"


def aggregate_by_family(runs: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for row in runs:
        fam = str(row.get("strategy_family") or strategy_family(str(row.get("strategy", ""))))
        buckets.setdefault(fam, []).append(row)

    out: dict[str, dict[str, Any]] = {}
    for fam, items in buckets.items():
        returns = [float(r.get("total_return_pct", 0)) for r in items]
        trades = [int(r.get("trade_count", 0)) for r in items]
        verdicts = [str(r.get("verdict", "")) for r in items]
        out[fam] = {
            "runs": len(items),
            "median_return_pct": sorted(returns)[len(returns) // 2] if returns else 0.0,
            "median_trades": sorted(trades)[len(trades) // 2] if trades else 0,
            "paper_candidate_count": sum(1 for v in verdicts if v == "paper_candidate"),
            "blocked_risk_count": sum(1 for v in verdicts if v == "blocked_risk"),
            "blocked_costs_count": sum(1 for v in verdicts if v == "blocked_costs"),
            "insufficient_trades_count": sum(1 for v in verdicts if v == "insufficient_trades"),
            "kill_count": sum(1 for v in verdicts if v == "kill"),
            "weak_count": sum(1 for v in verdicts if v == "weak"),
        }
    return out
