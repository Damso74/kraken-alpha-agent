"""Tests for regime features (Phase 18)."""

from __future__ import annotations

from src.bot.regime_features import compute_regime_features, summarize_regime_features
from tests.conftest_bot import synthetic_range, synthetic_uptrend


def test_regime_features_uptrend() -> None:
    candles = synthetic_uptrend(80)
    feat = compute_regime_features(candles, 60, ma_window=20, vol_lookback=10)
    assert feat is not None
    assert feat.close > feat.long_ma
    summary = summarize_regime_features(feat)
    assert "trend_strength" in summary


def test_regime_features_insufficient_history() -> None:
    candles = synthetic_uptrend(10)
    assert compute_regime_features(candles, 5, ma_window=20) is None


def test_regime_features_no_future_leakage() -> None:
    candles = synthetic_range(100)
    f1 = compute_regime_features(candles, 50)
    f2 = compute_regime_features(candles[:51], 50)
    assert f1 is not None and f2 is not None
    assert f1.close == f2.close
