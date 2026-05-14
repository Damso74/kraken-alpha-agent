from __future__ import annotations

from src.regime import (
    HIGH_VOL_15M,
    LOW_LIQUIDITY_VOLUME,
    TRENDING_RETURN_1H,
    classify,
)
from src.schemas import Features


def _features(**kwargs) -> Features:
    base = dict(
        symbol="TSLAx",
        last_price=100.0,
        bid=99.9,
        ask=100.1,
        spread_bps=10.0,
        return_5m=0.0,
        return_15m=0.0,
        return_1h=0.0,
        volatility_15m=0.001,
        volatility_1h=0.002,
        high_1h=101.0,
        low_1h=99.0,
        distance_from_high_1h=0.01,
        distance_from_low_1h=0.01,
        volume_1h=1000.0,
    )
    base.update(kwargs)
    return Features(**base)


def test_classify_low_liquidity():
    feats = _features(volume_1h=LOW_LIQUIDITY_VOLUME / 2)
    assert classify(feats) == "LOW_LIQUIDITY"


def test_classify_high_volatility():
    feats = _features(volatility_15m=HIGH_VOL_15M * 2)
    assert classify(feats) == "HIGH_VOLATILITY"


def test_classify_trending_up():
    feats = _features(return_1h=TRENDING_RETURN_1H * 2)
    assert classify(feats) == "TRENDING_UP"


def test_classify_trending_down():
    feats = _features(return_1h=-TRENDING_RETURN_1H * 2)
    assert classify(feats) == "TRENDING_DOWN"


def test_classify_ranging():
    feats = _features(return_1h=0.0001)
    assert classify(feats) == "RANGING"
