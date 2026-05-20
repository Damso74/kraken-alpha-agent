"""Rule-based regime classifier (Phase 18, explainable, no ML)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.bot.regime_features import RegimeFeatures

RegimeLabel = Literal["trend_up", "range", "high_vol", "panic", "unknown"]

PANIC_DRAWDOWN_THRESHOLD = 0.08
HIGH_VOL_PERCENTILE = 0.75
TREND_STRENGTH_MIN = 0.02
RANGE_TREND_MAX = 0.015


@dataclass(frozen=True)
class RegimeClassification:
    regime: RegimeLabel
    confidence: float
    reason: str


def classify_regime(features: RegimeFeatures | None) -> RegimeClassification:
    if features is None:
        return RegimeClassification("unknown", 0.0, "insufficient_history")

    if (
        features.drawdown_from_high >= PANIC_DRAWDOWN_THRESHOLD
        and features.volatility_percentile >= HIGH_VOL_PERCENTILE
        and features.close < features.long_ma
    ):
        return RegimeClassification(
            "panic",
            0.9,
            f"dd={features.drawdown_from_high:.2%} vol_pct={features.volatility_percentile:.2f}",
        )

    if features.volatility_percentile >= HIGH_VOL_PERCENTILE:
        return RegimeClassification(
            "high_vol",
            0.75,
            f"vol_pct={features.volatility_percentile:.2f}",
        )

    if (
        features.close > features.long_ma
        and features.moving_average_slope > 0
        and features.trend_strength >= TREND_STRENGTH_MIN
        and features.volatility_percentile < HIGH_VOL_PERCENTILE
    ):
        return RegimeClassification(
            "trend_up",
            0.8,
            f"slope={features.moving_average_slope:.4f} trend={features.trend_strength:.4f}",
        )

    if (
        features.trend_strength <= RANGE_TREND_MAX
        and features.volatility_percentile < HIGH_VOL_PERCENTILE
    ):
        return RegimeClassification(
            "range",
            0.7,
            f"range_score={features.range_score:.4f}",
        )

    return RegimeClassification("unknown", 0.4, "no_clear_regime")
