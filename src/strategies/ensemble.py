"""Ensemble combiner — weighted blend of strategy votes minus penalties.

Ensemble v2 adds a ``liquidity`` bonus when the symbol shows healthy
top-of-book and recent volume. Liquidity also dampens ``confidence`` so a
strong signal on a dead market does not produce an oversized position.
"""

from __future__ import annotations

from typing import Optional

from ..config import get_settings
from ..regime import classify
from ..schemas import Action, EnsembleResult, Features, StrategyVote
from ..utils import clamp


def _volatility_penalty(features: Features) -> float:
    return clamp(features.volatility_15m / 0.01, 0.0, 1.0)


def _spread_penalty(features: Features) -> float:
    return clamp(features.spread_bps / 80.0, 0.0, 1.0)


def combine(
    *,
    features: Features,
    votes: list[StrategyVote],
    liquidity_score: Optional[float] = None,
) -> EnsembleResult:
    cfg = get_settings().config.strategy
    risk = get_settings().config.risk
    w = cfg.ensemble_weights
    by_name = {v.name: v for v in votes}

    momentum = by_name.get("momentum", StrategyVote(name="momentum"))
    breakout = by_name.get("breakout", StrategyVote(name="breakout"))
    mean_rev = by_name.get("mean_reversion", StrategyVote(name="mean_reversion"))

    vol_pen = _volatility_penalty(features)
    spr_pen = _spread_penalty(features)

    # Liquidity defaults to "decent" so legacy callers that don't pass it
    # don't get penalised. Stays in [0, 1].
    liq = 0.6 if liquidity_score is None else clamp(float(liquidity_score), 0.0, 1.0)

    # The liquidity component reinforces the existing directional bias
    # rather than acting as a standalone score, so a strong-signal /
    # high-liquidity setup is rewarded more than the same signal on an
    # illiquid book.
    momentum_blend = (
        w.get("momentum", 0.4) * momentum.score
        + w.get("breakout", 0.25) * breakout.score
        + w.get("mean_reversion", 0.2) * mean_rev.score
    )
    liquidity_bonus = w.get("liquidity", 0.0) * liq * (1 if momentum_blend >= 0 else -1)

    final_score = (
        momentum_blend
        + liquidity_bonus
        - w.get("volatility_penalty", 0.1) * vol_pen
        - w.get("spread_penalty", 0.05) * spr_pen
    )
    final_score = clamp(final_score, -1.0, 1.0)

    if final_score >= cfg.thresholds.get("buy", 0.20):
        action: Action = "BUY"
    elif final_score <= cfg.thresholds.get("sell", -0.20):
        action = "SELL"
    else:
        action = "HOLD"

    avg_conf = (momentum.confidence + breakout.confidence + mean_rev.confidence) / 3
    confidence = clamp(
        avg_conf
        * (0.4 + 0.6 * liq)               # low liquidity caps confidence
        * (1 - 0.5 * vol_pen)
        * (1 - 0.3 * spr_pen),
        0.0,
        1.0,
    )

    base_size = get_settings().config.execution.dry_run_size_usd
    cap = max(base_size, risk.max_position_notional_usd)
    sized = abs(final_score) * cap * (0.5 + 0.5 * confidence)
    suggested_size = min(sized, risk.max_position_notional_usd)

    regime = classify(features)
    rationale = (
        f"score={final_score:+.3f} "
        f"(mom={momentum.score:+.2f}*{w.get('momentum')}, "
        f"brk={breakout.score:+.2f}*{w.get('breakout')}, "
        f"mr={mean_rev.score:+.2f}*{w.get('mean_reversion')}, "
        f"liq={liq:.2f}*{w.get('liquidity', 0.0)}) "
        f"vol_pen={vol_pen:.2f} spr_pen={spr_pen:.2f} regime={regime}"
    )
    return EnsembleResult(
        final_score=final_score,
        action=action,
        confidence=confidence,
        suggested_size_usd=suggested_size,
        votes=[momentum, breakout, mean_rev],
        regime=regime,
        rationale=rationale,
    )


__all__ = ["combine"]
