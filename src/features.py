"""Pure feature engineering on top of OHLC candles + ticker.

All functions here are deterministic and side-effect free so they can be
unit-tested without touching the network or the database.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .schemas import Features
from .utils import pct, safe_float


def _closes(candles: Sequence[dict]) -> list[float]:
    return [safe_float(c.get("close")) for c in candles if safe_float(c.get("close")) > 0]


def _last_close(candles: Sequence[dict]) -> float:
    closes = _closes(candles)
    return closes[-1] if closes else 0.0


def compute_return(candles: Sequence[dict], lookback: int) -> float:
    closes = _closes(candles)
    if len(closes) <= lookback or closes[-1 - lookback] == 0:
        return 0.0
    return closes[-1] / closes[-1 - lookback] - 1.0


def compute_log_returns(closes: Sequence[float]) -> list[float]:
    rets: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            rets.append(math.log(closes[i] / closes[i - 1]))
    return rets


def compute_volatility(candles: Sequence[dict], lookback: int) -> float:
    closes = _closes(candles)[-(lookback + 1):]
    rets = compute_log_returns(closes)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    variance = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(max(variance, 0.0))


def compute_spread_bps(bid: float | None, ask: float | None) -> float:
    bid = safe_float(bid)
    ask = safe_float(ask)
    if bid <= 0 or ask <= 0:
        return 0.0
    mid = (bid + ask) / 2
    if mid <= 0:
        return 0.0
    return (ask - bid) / mid * 10_000.0


def compute_high_low(candles: Sequence[dict], lookback: int) -> tuple[float, float]:
    window = list(candles)[-lookback:] if lookback else list(candles)
    if not window:
        return 0.0, 0.0
    high = max(safe_float(c.get("high")) for c in window)
    low = min(safe_float(c.get("low")) for c in window if safe_float(c.get("low")) > 0)
    return high, low


def compute_volume_sum(candles: Sequence[dict], lookback: int) -> float:
    return sum(safe_float(c.get("volume")) for c in list(candles)[-lookback:])


def compute_features(
    *,
    symbol: str,
    ticker: dict,
    candles: Sequence[dict],
    candle_interval_minutes: int = 60,
) -> Features:
    """Compose the canonical Features record from raw inputs."""
    closes = _closes(candles)
    last_price = _last_close(candles) or safe_float(ticker.get("last"))
    bid = safe_float(ticker.get("bid"))
    ask = safe_float(ticker.get("ask"))

    # Convert "5m / 15m / 1h" lookbacks to number of candles given interval.
    per_5m = max(1, round(5 / candle_interval_minutes)) if candle_interval_minutes <= 5 else 1
    per_15m = max(1, round(15 / candle_interval_minutes)) if candle_interval_minutes <= 15 else 1
    per_1h = max(1, round(60 / candle_interval_minutes))

    return_5m = compute_return(candles, per_5m)
    return_15m = compute_return(candles, per_15m)
    return_1h = compute_return(candles, per_1h)
    vol_15m = compute_volatility(candles, per_15m)
    vol_1h = compute_volatility(candles, per_1h)

    high_1h, low_1h = compute_high_low(candles, max(per_1h, 1))
    dist_from_high = pct(high_1h - last_price, high_1h) if high_1h else 0.0
    dist_from_low = pct(last_price - low_1h, low_1h) if low_1h else 0.0

    return Features(
        symbol=symbol,
        last_price=last_price,
        bid=bid or None,
        ask=ask or None,
        spread_bps=compute_spread_bps(bid, ask),
        return_5m=return_5m,
        return_15m=return_15m,
        return_1h=return_1h,
        volatility_15m=vol_15m,
        volatility_1h=vol_1h,
        high_1h=high_1h,
        low_1h=low_1h,
        distance_from_high_1h=dist_from_high,
        distance_from_low_1h=dist_from_low,
        volume_1h=compute_volume_sum(candles, per_1h),
        source=str(ticker.get("source", "kraken_cli")),
    )


__all__ = [
    "compute_return",
    "compute_volatility",
    "compute_spread_bps",
    "compute_high_low",
    "compute_volume_sum",
    "compute_features",
    "compute_log_returns",
]
