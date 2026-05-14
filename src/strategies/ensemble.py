"""Ensemble combiner — weighted blend of strategy votes minus penalties."""

from __future__ import annotations

from ..config import get_settings
from ..regime import classify
from ..schemas import Action, EnsembleResult, Features, StrategyVote
from ..utils import clamp


# Penalties operate on features directly so weights stay in [0, 1] range.
def _volatility_penalty(features: Features) -> float:
    return clamp(features.volatility_15m / 0.01, 0.0, 1.0)


def _spread_penalty(features: Features) -> float:
    return clamp(features.spread_bps / 80.0, 0.0, 1.0)


def combine(
    *,
    features: Features,
    votes: list[StrategyVote],
) -> EnsembleResult:
    cfg = get_settings().config.strategy
    w = cfg.ensemble_weights
    by_name = {v.name: v for v in votes}

    momentum = by_name.get("momentum", StrategyVote(name="momentum"))
    breakout = by_name.get("breakout", StrategyVote(name="breakout"))
    mean_rev = by_name.get("mean_reversion", StrategyVote(name="mean_reversion"))

    vol_pen = _volatility_penalty(features)
    spr_pen = _spread_penalty(features)

    final_score = (
        w.get("momentum", 0.4) * momentum.score
        + w.get("breakout", 0.25) * breakout.score
        + w.get("mean_reversion", 0.2) * mean_rev.score
        - w.get("volatility_penalty", 0.1) * vol_pen
        - w.get("spread_penalty", 0.05) * spr_pen
    )
    final_score = clamp(final_score, -1.0, 1.0)

    if final_score >= cfg.thresholds.get("buy", 0.35):
        action: Action = "BUY"
    elif final_score <= cfg.thresholds.get("sell", -0.35):
        action = "SELL"
    else:
        action = "HOLD"

    # Confidence is a blend of per-strategy confidences, dampened by penalties.
    avg_conf = (momentum.confidence + breakout.confidence + mean_rev.confidence) / 3
    confidence = clamp(avg_conf * (1 - 0.5 * vol_pen) * (1 - 0.3 * spr_pen), 0.0, 1.0)

    base_size = get_settings().config.execution.dry_run_size_usd
    suggested_size = abs(final_score) * base_size

    regime = classify(features)
    rationale = (
        f"score={final_score:+.3f} (mom={momentum.score:+.2f}*{w.get('momentum')}, "
        f"brk={breakout.score:+.2f}*{w.get('breakout')}, "
        f"mr={mean_rev.score:+.2f}*{w.get('mean_reversion')}) "
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
