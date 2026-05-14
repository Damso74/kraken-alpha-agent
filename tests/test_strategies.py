from __future__ import annotations

from src.schemas import Features
from src.strategies import (
    breakout_score,
    combine,
    mean_reversion_score,
    momentum_score,
)


def _features(**kwargs) -> Features:
    base = dict(
        symbol="NVDAx",
        last_price=100.0,
        bid=99.95,
        ask=100.05,
        spread_bps=5.0,
        return_5m=0.0,
        return_15m=0.0,
        return_1h=0.0,
        volatility_15m=0.002,
        volatility_1h=0.003,
        high_1h=101.0,
        low_1h=99.0,
        distance_from_high_1h=0.005,
        distance_from_low_1h=0.005,
        volume_1h=2_000.0,
    )
    base.update(kwargs)
    return Features(**base)


def test_momentum_positive_for_uptrend():
    f = _features(return_5m=0.005, return_15m=0.01, return_1h=0.02)
    v = momentum_score(f)
    assert v.score > 0.3
    assert v.confidence > 0.1


def test_momentum_negative_for_downtrend():
    f = _features(return_5m=-0.005, return_15m=-0.01, return_1h=-0.02)
    v = momentum_score(f)
    assert v.score < -0.3


def test_breakout_positive_near_high():
    f = _features(distance_from_high_1h=0.0001, distance_from_low_1h=0.02)
    v = breakout_score(f)
    assert v.score > 0


def test_breakout_negative_near_low():
    f = _features(distance_from_high_1h=0.02, distance_from_low_1h=0.0001)
    v = breakout_score(f)
    assert v.score < 0


def test_mean_reversion_fades_sharp_15m_move():
    f = _features(return_15m=0.02, return_1h=0.001)
    v = mean_reversion_score(f)
    assert v.score < 0  # expect a fade (SELL bias) after a 2% 15m spike


def test_ensemble_buy_on_strong_trend():
    f = _features(return_5m=0.005, return_15m=0.01, return_1h=0.02, distance_from_high_1h=0.0001)
    votes = [momentum_score(f), breakout_score(f), mean_reversion_score(f)]
    result = combine(features=f, votes=votes)
    assert result.action == "BUY"
    assert result.final_score > 0
    assert 0 <= result.confidence <= 1
    assert result.suggested_size_usd >= 0


def test_ensemble_hold_on_quiet_market():
    f = _features()
    votes = [momentum_score(f), breakout_score(f), mean_reversion_score(f)]
    result = combine(features=f, votes=votes)
    assert result.action == "HOLD"
