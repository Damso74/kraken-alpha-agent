"""Tests for regime classifier (Phase 18)."""

from __future__ import annotations

from src.bot.regime_classifier import classify_regime
from src.bot.regime_features import RegimeFeatures


def test_classify_trend_up() -> None:
    feat = RegimeFeatures(
        trend_strength=0.05,
        moving_average_slope=0.002,
        realized_vol=0.01,
        volatility_percentile=0.4,
        range_score=0.02,
        drawdown_from_high=0.02,
        close=110.0,
        long_ma=105.0,
    )
    c = classify_regime(feat)
    assert c.regime == "trend_up"


def test_classify_panic() -> None:
    feat = RegimeFeatures(
        trend_strength=0.05,
        moving_average_slope=-0.01,
        volatility_percentile=0.9,
        drawdown_from_high=0.12,
        close=90.0,
        long_ma=100.0,
    )
    c = classify_regime(feat)
    assert c.regime == "panic"


def test_classify_unknown_insufficient() -> None:
    c = classify_regime(None)
    assert c.regime == "unknown"
