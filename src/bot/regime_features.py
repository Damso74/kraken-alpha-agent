"""Regime feature engine for paper-bot router (no future leakage)."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RegimeFeatures:
    trend_strength: float = 0.0
    moving_average_slope: float = 0.0
    realized_vol: float = 0.0
    volatility_percentile: float = 0.0
    range_score: float = 0.0
    drawdown_from_high: float = 0.0
    breakout_pressure: float = 0.0
    volume_zscore: float = 0.0
    bar_index: int = 0
    close: float = 0.0
    long_ma: float = 0.0


def _closes(candles: Sequence[Any], end: int) -> list[float]:
    out: list[float] = []
    for i in range(end + 1):
        c = candles[i]
        if isinstance(c, Mapping):
            out.append(float(c["close"]))
        else:
            out.append(float(c.close))
    return out


def _volumes(candles: Sequence[Any], end: int) -> list[float]:
    out: list[float] = []
    for i in range(end + 1):
        c = candles[i]
        if isinstance(c, Mapping):
            out.append(float(c.get("volume", 0.0)))
        else:
            out.append(float(getattr(c, "volume", 0.0)))
    return out


def _sma(values: Sequence[float], window: int) -> float:
    if len(values) < window or window <= 0:
        return values[-1] if values else 0.0
    chunk = values[-window:]
    return sum(chunk) / len(chunk)


def _realized_vol(closes: Sequence[float], lookback: int) -> float:
    if len(closes) < lookback + 1:
        return 0.0
    rets: list[float] = []
    for i in range(len(closes) - lookback, len(closes)):
        if closes[i - 1] > 1e-12:
            rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
    if len(rets) < 2:
        return 0.0
    return statistics.pstdev(rets)


def compute_regime_features(
    candles: Sequence[Any],
    index: int,
    *,
    ma_window: int = 50,
    vol_lookback: int = 20,
    range_lookback: int = 20,
    vol_history: int = 60,
) -> RegimeFeatures | None:
    """Compute features using only candles[:index+1] (inclusive)."""
    if index < ma_window or index < vol_lookback:
        return None

    closes = _closes(candles, index)
    volumes = _volumes(candles, index)
    close = closes[-1]
    long_ma = _sma(closes, ma_window)
    prev_ma = _sma(closes[:-1], ma_window) if len(closes) > ma_window else long_ma
    slope = (long_ma - prev_ma) / prev_ma if abs(prev_ma) > 1e-12 else 0.0

    realized = _realized_vol(closes, vol_lookback)
    vol_series: list[float] = []
    for j in range(vol_lookback + 1, len(closes)):
        vol_series.append(_realized_vol(closes[: j + 1], vol_lookback))
    vol_pct = 0.5
    if vol_series:
        below = sum(1 for v in vol_series if v <= realized)
        vol_pct = below / len(vol_series)

    window_closes = closes[-range_lookback:]
    hi = max(window_closes)
    lo = min(window_closes)
    range_score = (hi - lo) / close if close > 1e-12 else 0.0
    trend_strength = abs(close - long_ma) / close if close > 1e-12 else 0.0

    peak = max(closes[-vol_history:]) if len(closes) >= vol_history else max(closes)
    dd = (peak - close) / peak if peak > 1e-12 else 0.0

    prior_high = max(closes[-range_lookback - 1 : -1]) if len(closes) > range_lookback else close
    breakout_pressure = (close - prior_high) / close if close > 1e-12 else 0.0

    vol_z = 0.0
    if len(volumes) >= vol_lookback:
        chunk = volumes[-vol_lookback:]
        mean_v = statistics.mean(chunk)
        stdev_v = statistics.pstdev(chunk) if len(chunk) > 1 else 0.0
        if stdev_v > 1e-12:
            vol_z = (volumes[-1] - mean_v) / stdev_v

    return RegimeFeatures(
        trend_strength=trend_strength,
        moving_average_slope=slope,
        realized_vol=realized,
        volatility_percentile=vol_pct,
        range_score=range_score,
        drawdown_from_high=dd,
        breakout_pressure=breakout_pressure,
        volume_zscore=vol_z,
        bar_index=index,
        close=close,
        long_ma=long_ma,
    )


def summarize_regime_features(features: RegimeFeatures) -> dict[str, float]:
    return {
        "trend_strength": round(features.trend_strength, 6),
        "moving_average_slope": round(features.moving_average_slope, 6),
        "realized_vol": round(features.realized_vol, 6),
        "volatility_percentile": round(features.volatility_percentile, 4),
        "range_score": round(features.range_score, 6),
        "drawdown_from_high": round(features.drawdown_from_high, 6),
        "breakout_pressure": round(features.breakout_pressure, 6),
        "volume_zscore": round(features.volume_zscore, 4),
        "close": round(features.close, 4),
        "long_ma": round(features.long_ma, 4),
    }
