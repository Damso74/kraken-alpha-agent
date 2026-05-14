from __future__ import annotations

import pytest

from src.features import (
    compute_features,
    compute_return,
    compute_spread_bps,
    compute_volatility,
)


def _candles(prices: list[float]) -> list[dict]:
    out = []
    for i, p in enumerate(prices):
        out.append({
            "timestamp": i,
            "open": p,
            "high": p * 1.001,
            "low": p * 0.999,
            "close": p,
            "vwap": p,
            "volume": 1_000.0,
        })
    return out


def test_compute_return_basic():
    candles = _candles([100, 101, 102, 103, 105])
    assert compute_return(candles, 1) == pytest.approx((105 - 103) / 103)
    assert compute_return(candles, 4) == pytest.approx((105 - 100) / 100)


def test_compute_return_handles_short_series():
    assert compute_return([], 1) == 0.0
    assert compute_return(_candles([100]), 2) == 0.0


def test_volatility_zero_for_flat_prices():
    candles = _candles([100] * 10)
    assert compute_volatility(candles, 5) == 0.0


def test_volatility_positive_for_noisy_prices():
    candles = _candles([100, 102, 98, 104, 99, 105, 96, 107, 95, 108])
    vol = compute_volatility(candles, 5)
    assert vol > 0


def test_spread_bps_handles_zero():
    assert compute_spread_bps(0, 0) == 0.0
    assert compute_spread_bps(None, 100) == 0.0


def test_spread_bps_positive():
    bps = compute_spread_bps(99.95, 100.05)
    assert 9.0 < bps < 11.0  # ~10 bps


def test_compute_features_returns_consistent_record():
    candles = _candles([100 + i for i in range(24)])
    ticker = {"last": 123.0, "bid": 122.9, "ask": 123.1, "source": "mock"}
    feats = compute_features(symbol="TSLAx", ticker=ticker, candles=candles)
    assert feats.symbol == "TSLAx"
    assert feats.last_price == candles[-1]["close"]
    assert feats.return_1h > 0  # rising series
    assert feats.high_1h >= feats.low_1h
    assert feats.spread_bps > 0
