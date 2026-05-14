"""Momentum strategy — leans on short-horizon returns."""

from __future__ import annotations

from ..schemas import Features, StrategyVote
from ..utils import clamp


def score(features: Features) -> StrategyVote:
    r5 = features.return_5m
    r15 = features.return_15m
    r1h = features.return_1h
    raw = 0.5 * r1h + 0.3 * r15 + 0.2 * r5
    # Saturating non-linearity so a 2% jump scores ~+1 and a 2% drop scores ~-1.
    saturated = clamp(raw / 0.02, -1.0, 1.0)
    # Confidence increases with the magnitude of the move and stays bounded.
    magnitude = (abs(r5) + abs(r15) + abs(r1h)) / 3
    confidence = clamp(magnitude / 0.01, 0.0, 1.0)
    rationale = (
        f"r1h={r1h:+.3%} r15m={r15:+.3%} r5m={r5:+.3%} -> raw={raw:+.4f}"
    )
    return StrategyVote(
        name="momentum",
        score=saturated,
        confidence=confidence,
        rationale=rationale,
    )
