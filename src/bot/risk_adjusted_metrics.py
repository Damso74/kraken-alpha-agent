"""Risk-adjusted metrics vs buy-and-hold (Phase 23)."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from src.bot.journal import BotJournal
from src.bot.metrics import _max_drawdown


def _underwater_segments(equity_curve: Sequence[float]) -> list[float]:
    if len(equity_curve) < 2:
        return []
    peak = equity_curve[0]
    underwater: list[float] = []
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        if peak > 1e-12:
            dd = (peak - eq) / peak * 100.0
            underwater.append(dd)
    return underwater


def ulcer_index_proxy(equity_curve: Sequence[float]) -> float:
    """Ulcer Index proxy: RMS of percentage drawdowns from running peak."""
    uw = _underwater_segments(equity_curve)
    if not uw:
        return 0.0
    return math.sqrt(sum(d * d for d in uw) / len(uw))


def calmar_like(return_pct: float, max_drawdown_pct: float) -> float:
    if max_drawdown_pct <= 1e-9:
        return return_pct if return_pct > 0 else 0.0
    return return_pct / max_drawdown_pct


def estimate_time_in_market_pct(
    journal: BotJournal | None,
    *,
    warmup_bars: int,
    total_bars: int,
) -> float:
    """Fraction of post-warmup bars with an open position (from fill journal)."""
    usable = max(1, total_bars - warmup_bars)
    if journal is None or not journal.trades:
        return 0.0
    intervals: list[tuple[int, int]] = []
    open_bar: int | None = None
    for t in journal.trades:
        bar = int(t.get("bar_index", 0))
        side = str(t.get("side", "")).lower()
        if side == "buy" and open_bar is None:
            open_bar = bar
        elif side == "sell" and open_bar is not None:
            intervals.append((open_bar, bar))
            open_bar = None
    if open_bar is not None:
        intervals.append((open_bar, total_bars - 1))
    held = sum(max(0, end - start) for start, end in intervals)
    return min(1.0, held / usable)


def drawdown_reduction_vs_bh(strategy_dd_pct: float, bh_dd_pct: float) -> float:
    """Positive when strategy drawdown is lower than buy-and-hold."""
    return bh_dd_pct - strategy_dd_pct


def risk_adjusted_alpha(
    strategy_return_pct: float,
    bh_return_pct: float,
    strategy_max_dd_pct: float,
) -> float:
    """Excess return scaled by strategy max drawdown (Calmar-style alpha)."""
    excess = strategy_return_pct - bh_return_pct
    if strategy_max_dd_pct <= 1e-9:
        return excess
    return excess / strategy_max_dd_pct


def compute_risk_adjusted_bundle(
    *,
    equity_curve: Sequence[float],
    strategy_return_pct: float,
    strategy_max_dd_pct: float,
    bh_return_pct: float,
    bh_max_dd_pct: float,
    journal: BotJournal | None = None,
    warmup_bars: int = 0,
    total_bars: int = 0,
) -> dict[str, float]:
    tim = estimate_time_in_market_pct(
        journal,
        warmup_bars=warmup_bars,
        total_bars=total_bars or len(equity_curve),
    )
    return {
        "calmar_like": round(calmar_like(strategy_return_pct, strategy_max_dd_pct), 4),
        "ulcer_index": round(ulcer_index_proxy(equity_curve), 4),
        "time_in_market_pct": round(tim * 100.0, 2),
        "drawdown_reduction_vs_bh": round(
            drawdown_reduction_vs_bh(strategy_max_dd_pct, bh_max_dd_pct), 4
        ),
        "risk_adjusted_alpha": round(
            risk_adjusted_alpha(
                strategy_return_pct, bh_return_pct, strategy_max_dd_pct
            ),
            4,
        ),
        "bh_return_pct": round(bh_return_pct, 4),
        "bh_max_drawdown_pct": round(bh_max_dd_pct, 4),
    }


def risk_adjusted_to_dict(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return dict(bundle)
