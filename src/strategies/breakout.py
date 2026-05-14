"""Breakout strategy — distance from the 1h high/low."""

from __future__ import annotations

from ..schemas import Features, StrategyVote
from ..utils import clamp


def score(features: Features) -> StrategyVote:
    # Proximity is 1.0 when the price sits exactly on the 1h extreme and 0
    # when it is more than ~50bps away. The breakout score is just the
    # difference: positive near the high, negative near the low.
    threshold = 0.005
    prox_high = clamp(1.0 - features.distance_from_high_1h / threshold, 0.0, 1.0)
    prox_low = clamp(1.0 - features.distance_from_low_1h / threshold, 0.0, 1.0)
    saturated = clamp(prox_high - prox_low, -1.0, 1.0)
    confidence = clamp(max(prox_high, prox_low), 0.0, 1.0)
    rationale = (
        f"dist_high={features.distance_from_high_1h:.4f} "
        f"dist_low={features.distance_from_low_1h:.4f} -> "
        f"prox_high={prox_high:.3f} prox_low={prox_low:.3f}"
    )
    return StrategyVote(
        name="breakout",
        score=saturated,
        confidence=confidence,
        rationale=rationale,
    )
