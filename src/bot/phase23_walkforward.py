"""Phase 23 walk-forward verdict extensions (buy-and-hold gates)."""

from __future__ import annotations

from typing import Any, Mapping

from src.bot.walkforward_metrics import (
    WalkForwardAggregate,
    WalkForwardVerdictResult,
    classify_walkforward_verdict,
)

MIN_TOTAL_TRADES_PHASE23 = 8
MAX_TURNOVER_RATIO = 25.0
MIN_ASSETS_FOR_DOMINANCE = 2
DOMINANCE_RETURN_SHARE = 0.85


def classify_phase23_walkforward_verdict(
    agg: WalkForwardAggregate,
    context: Mapping[str, Any] | None = None,
) -> WalkForwardVerdictResult:
    """Strict WF + Phase 23 buy-and-hold / concentration gates."""
    base = classify_walkforward_verdict(agg, context)
    ctx = dict(context or {})
    if base.verdict != "paper_candidate_walkforward":
        return base

    extra: list[str] = []
    bh_dd = float(ctx.get("bh_max_drawdown_pct", 0.0))
    strat_dd = float(ctx.get("full_max_drawdown_pct", agg.max_window_drawdown))
    if bh_dd > 1e-9 and strat_dd >= bh_dd - 0.5:
        extra.append(
            f"drawdown_not_below_bh strat={strat_dd:.2f}% bh={bh_dd:.2f}%"
        )

    total_trades = int(ctx.get("total_trade_count", 0))
    if total_trades < MIN_TOTAL_TRADES_PHASE23:
        extra.append(f"total_trade_count={total_trades} < {MIN_TOTAL_TRADES_PHASE23}")

    turnover = float(ctx.get("turnover_ratio", 0.0))
    if turnover > MAX_TURNOVER_RATIO:
        extra.append(f"turnover_ratio={turnover:.2f} > {MAX_TURNOVER_RATIO}")

    asset_returns: dict[str, float] = ctx.get("asset_returns") or {}
    if len(asset_returns) >= MIN_ASSETS_FOR_DOMINANCE:
        total_abs = sum(abs(v) for v in asset_returns.values()) or 1.0
        best_asset = max(asset_returns, key=lambda k: abs(asset_returns[k]))
        if abs(asset_returns[best_asset]) / total_abs > DOMINANCE_RETURN_SHARE:
            extra.append(f"single_asset_dominance={best_asset}")

    if extra:
        return WalkForwardVerdictResult(
            "validation_candidate",
            base.reasons + extra,
            aggregate=agg,
        )
    return base
