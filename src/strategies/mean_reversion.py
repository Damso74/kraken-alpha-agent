"""Mean-reversion strategy — fades extreme short-horizon moves."""

from __future__ import annotations

from ..schemas import Features, StrategyVote
from ..utils import clamp


def score(features: Features) -> StrategyVote:
    # Strong 15m move tends to revert — sign is inverted.
    r15 = features.return_15m
    r1h = features.return_1h
    overshoot = (r15 - r1h * 0.3)
    raw = -clamp(overshoot / 0.01, -1.0, 1.0)
    confidence = clamp(abs(overshoot) / 0.005, 0.0, 1.0)
    # Don't fade when 15m and 1h agree (likely a real trend).
    if r15 * r1h > 0 and abs(r1h) >= 0.005:
        confidence *= 0.5
    rationale = (
        f"overshoot15m_vs_1h={overshoot:+.4f} -> fade_score={raw:+.3f}"
    )
    return StrategyVote(
        name="mean_reversion",
        score=raw,
        confidence=confidence,
        rationale=rationale,
    )
