"""Market-regime classifier (rule-based, intentionally simple)."""

from __future__ import annotations

from .schemas import Features, Regime

# Thresholds tuned for hourly candles on US equities. Values are deliberately
# conservative — the agent should err on the side of HOLD/UNKNOWN.
TRENDING_RETURN_1H = 0.004        # 0.4% in one hour
RANGING_RETURN_1H = 0.001
HIGH_VOL_15M = 0.012              # ~1.2% std on 15m log returns
LOW_LIQUIDITY_VOLUME = 200.0


def classify(features: Features) -> Regime:
    if features.volume_1h <= LOW_LIQUIDITY_VOLUME:
        return "LOW_LIQUIDITY"
    if features.volatility_15m >= HIGH_VOL_15M:
        return "HIGH_VOLATILITY"
    if features.return_1h >= TRENDING_RETURN_1H:
        return "TRENDING_UP"
    if features.return_1h <= -TRENDING_RETURN_1H:
        return "TRENDING_DOWN"
    if abs(features.return_1h) <= RANGING_RETURN_1H:
        return "RANGING"
    return "UNKNOWN"


__all__ = ["classify", "TRENDING_RETURN_1H", "HIGH_VOL_15M", "LOW_LIQUIDITY_VOLUME"]
