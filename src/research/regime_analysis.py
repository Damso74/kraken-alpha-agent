"""Regime labeling and cross-regime robustness checks (research-only).

This module assigns **point-in-time** regime labels to a price or
return series and summarises how a metric (typically an event-study
forward return) behaves conditional on those labels. It is the G2
*regime robustness* companion to :mod:`src.research.event_study` —
it answers "does the effect survive when we slice by trend, volatility
or calendar session?" without importing any live-trading code.

Hard contract
-------------
- **Stdlib only** (:mod:`math`, :mod:`statistics`, :mod:`datetime`).
- **No lookahead.** Every label at index ``i`` uses information
  available at or before ``i`` only. Thresholds (vol quantiles,
  trend returns) never peek at future observations.
- **Deterministic.** Pure functions; same inputs → same outputs.
- **No network I/O, no order placement.** Must not import
  :mod:`src.execution`, :mod:`src.futures_kraken_cli`, :mod:`src.risk`
  or :mod:`src.kraken_cli`.

Regime vocabulary
-----------------
- Trend: ``"bull"`` | ``"bear"`` | ``"sideways"`` | ``None`` (warm-up)
- Volatility: ``"high"`` | ``"low"`` | ``None`` (warm-up)
- Calendar: ``"weekend"`` | ``"weekday"`` (UTC Saturday/Sunday)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from ..logger import get_logger

logger = get_logger(__name__)

_ET = ZoneInfo("America/New_York")

# Defaults tuned for daily crypto OHLC; callers may override.
DEFAULT_TREND_LOOKBACK = 20
DEFAULT_BULL_THRESHOLD = 0.02
DEFAULT_BEAR_THRESHOLD = 0.02
DEFAULT_VOL_LOOKBACK = 20
DEFAULT_VOL_QUANTILE = 0.5
DEFAULT_MIN_REGIME_COUNT = 5
DEFAULT_MAX_SPREAD_RATIO = 0.5

TrendRegime = Optional[str]
VolRegime = Optional[str]
CalendarRegime = str


@dataclass(frozen=True)
class RegimeSummary:
    """Descriptive stats for one regime bucket."""

    regime: str
    count: int
    mean: float
    median: float
    stdev: Optional[float]


@dataclass(frozen=True)
class RegimeStabilityResult:
    """Verdict on whether a metric is stable across regime slices."""

    label: str
    dominant_regime: Optional[str]
    min_mean: Optional[float]
    max_mean: Optional[float]
    spread_ratio: Optional[float]
    per_regime: tuple[RegimeSummary, ...]
    notes: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _positive_closes(closes: Sequence[float]) -> list[float]:
    out: list[float] = []
    for raw in closes:
        try:
            c = float(raw)
        except (TypeError, ValueError):
            out.append(float("nan"))
            continue
        if not math.isfinite(c) or c <= 0:
            out.append(float("nan"))
        else:
            out.append(c)
    return out


def _log_returns(closes: Sequence[float]) -> list[float]:
    """Log returns aligned to close index (index 0 is always NaN)."""
    out: list[float] = [float("nan")]
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if not math.isfinite(prev) or not math.isfinite(cur) or prev <= 0 or cur <= 0:
            out.append(float("nan"))
        else:
            out.append(math.log(cur / prev))
    return out


def _rolling_stdev(values: Sequence[float], window: int) -> list[Optional[float]]:
    """Sample stdev of ``values[start:i+1]`` with width ``window``."""
    if window < 2:
        return [None for _ in values]
    out: list[Optional[float]] = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = [float(v) for v in values[start : i + 1] if math.isfinite(v)]
        if len(chunk) < window:
            out.append(None)
            continue
        try:
            sd = statistics.stdev(chunk)
        except statistics.StatisticsError:
            out.append(None)
            continue
        out.append(sd if math.isfinite(sd) else None)
    return out


def _quantile(sorted_values: Sequence[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    idx = (len(sorted_values) - 1) * p
    lo = int(math.floor(idx))
    hi = min(lo + 1, len(sorted_values) - 1)
    weight = idx - lo
    return sorted_values[lo] * (1.0 - weight) + sorted_values[hi] * weight


def _extract_close(row: Mapping[str, Any]) -> Optional[float]:
    val = row.get("close")
    if val is None:
        return None
    try:
        c = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(c) or c <= 0:
        return None
    return c


def _extract_timestamp(row: Mapping[str, Any]) -> Optional[int]:
    val = row.get("timestamp")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public assigners
# ---------------------------------------------------------------------------


def assign_trend_regime(
    closes: Sequence[float],
    *,
    lookback: int = DEFAULT_TREND_LOOKBACK,
    bull_threshold: float = DEFAULT_BULL_THRESHOLD,
    bear_threshold: float = DEFAULT_BEAR_THRESHOLD,
) -> list[TrendRegime]:
    """Label each close with a trend regime using a trailing return.

    At index ``i`` (once ``i >= lookback``) the reference return is

    ``(close[i] - close[i - lookback]) / close[i - lookback]``.

    Labels
    ------
    - ``"bull"`` when return ``> bull_threshold``
    - ``"bear"`` when return ``< -bear_threshold``
    - ``"sideways"`` otherwise
    - ``None`` during warm-up (``i < lookback``) or when prices are invalid
    """
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    if bull_threshold < 0 or bear_threshold < 0:
        raise ValueError("thresholds must be non-negative")

    prices = _positive_closes(closes)
    out: list[TrendRegime] = [None] * len(prices)

    for i in range(lookback, len(prices)):
        cur = prices[i]
        base = prices[i - lookback]
        if not math.isfinite(cur) or not math.isfinite(base) or base <= 0:
            out[i] = None
            continue
        ret = (cur - base) / base
        if ret > bull_threshold:
            out[i] = "bull"
        elif ret < -bear_threshold:
            out[i] = "bear"
        else:
            out[i] = "sideways"
    return out


def assign_volatility_regime(
    closes: Sequence[float],
    *,
    lookback: int = DEFAULT_VOL_LOOKBACK,
    quantile: float = DEFAULT_VOL_QUANTILE,
) -> list[VolRegime]:
    """Label each close with ``"high"`` or ``"low"`` realised volatility.

    Steps (no lookahead at index ``i``):

    1. Compute log-returns from ``closes``.
    2. Rolling sample stdev of log-returns with width ``lookback``.
    3. Compare the rolling stdev at ``i`` to the ``quantile`` of rolling
       stdevs observed strictly **before** ``i`` (indices
       ``[lookback, i - 1]``). The current stdev is **not** included in
       the reference distribution.
    4. Above the quantile → ``"high"``; at or below → ``"low"``.

    Returns ``None`` until at least one prior rolling stdev exists.
    """
    if lookback < 2:
        raise ValueError("lookback must be >= 2")
    if not (0.0 < quantile < 1.0):
        raise ValueError("quantile must be in (0, 1)")

    prices = _positive_closes(closes)
    rets = _log_returns(prices)
    rolling = _rolling_stdev(rets, lookback)
    out: list[VolRegime] = [None] * len(prices)

    for i in range(len(prices)):
        current = rolling[i]
        if current is None:
            continue
        past = [v for v in rolling[lookback:i] if v is not None]
        if not past:
            continue
        threshold = _quantile(sorted(past), quantile)
        if not math.isfinite(threshold):
            continue
        out[i] = "high" if current > threshold else "low"
    return out


def assign_calendar_regime(
    timestamps: Sequence[int],
    *,
    use_utc: bool = True,
) -> list[CalendarRegime]:
    """Label each timestamp as ``"weekend"`` or ``"weekday"``.

    Weekend = Saturday or Sunday. By default the weekday is evaluated in
    UTC (``use_utc=True``), matching the daily-crypto convention in
    :mod:`src.signals.calendar_effects`.
    """
    tz = timezone.utc if use_utc else _ET
    out: list[CalendarRegime] = []
    for ts in timestamps:
        try:
            ts_int = int(ts)
        except (TypeError, ValueError):
            out.append("weekday")
            continue
        dt = datetime.fromtimestamp(ts_int, tz=tz)
        if dt.weekday() >= 5:
            out.append("weekend")
        else:
            out.append("weekday")
    return out


def assign_calendar_regime_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    use_utc: bool = True,
) -> list[CalendarRegime]:
    """Convenience wrapper: extract ``timestamp`` from OHLC rows."""
    timestamps: list[int] = []
    for row in rows:
        ts = _extract_timestamp(row)
        timestamps.append(ts if ts is not None else 0)
    return assign_calendar_regime(timestamps, use_utc=use_utc)


# ---------------------------------------------------------------------------
# Summarisation & stability
# ---------------------------------------------------------------------------


def summarize_by_regime(
    values: Sequence[float],
    regimes: Sequence[Optional[str]],
    *,
    min_count: int = 1,
) -> tuple[RegimeSummary, ...]:
    """Aggregate ``values`` by parallel ``regimes`` labels.

    Pairs where ``regime is None`` or ``value`` is non-finite are skipped.
    Regimes with ``count < min_count`` are omitted from the output.
    """
    if len(values) != len(regimes):
        raise ValueError("values and regimes must have the same length")
    if min_count < 1:
        raise ValueError("min_count must be >= 1")

    buckets: dict[str, list[float]] = {}
    for val, regime in zip(values, regimes):
        if regime is None:
            continue
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(f):
            continue
        buckets.setdefault(str(regime), []).append(f)

    summaries: list[RegimeSummary] = []
    for regime in sorted(buckets):
        chunk = buckets[regime]
        if len(chunk) < min_count:
            continue
        mean = statistics.mean(chunk)
        med = statistics.median(chunk)
        sd: Optional[float]
        if len(chunk) >= 2:
            try:
                sd = statistics.stdev(chunk)
            except statistics.StatisticsError:
                sd = None
        else:
            sd = None
        summaries.append(
            RegimeSummary(
                regime=regime,
                count=len(chunk),
                mean=mean,
                median=med,
                stdev=sd,
            )
        )
    return tuple(summaries)


def classify_regime_stability(
    summaries: Sequence[RegimeSummary],
    *,
    min_per_regime: int = DEFAULT_MIN_REGIME_COUNT,
    max_spread_ratio: float = DEFAULT_MAX_SPREAD_RATIO,
) -> RegimeStabilityResult:
    """Decide whether a metric is **stable** across regime slices.

    Verdicts
    --------
    ``"insufficient_data"``
        Fewer than two regimes, or any regime with ``count < min_per_regime``.
    ``"single_regime"``
        Only one regime bucket passed ``min_per_regime`` (nothing to compare).
    ``"stable"``
        All regime means share the same sign **and**
        ``(max_mean - min_mean) / max(|mean|) <= max_spread_ratio``.
    ``"unstable"``
        Sign flip across regimes **or** spread ratio exceeds the cap.

    ``spread_ratio`` uses ``max(|mean|)`` across regimes as the denominator;
    when all means are zero the ratio is defined as ``0.0``.
    """
    if min_per_regime < 1:
        raise ValueError("min_per_regime must be >= 1")
    if max_spread_ratio < 0:
        raise ValueError("max_spread_ratio must be non-negative")

    per = tuple(summaries)
    eligible = [s for s in per if s.count >= min_per_regime]

    if not eligible:
        return RegimeStabilityResult(
            label="insufficient_data",
            dominant_regime=None,
            min_mean=None,
            max_mean=None,
            spread_ratio=None,
            per_regime=per,
            notes="no regime bucket meets min_per_regime",
        )

    if len(eligible) < 2:
        dom = max(eligible, key=lambda s: s.count)
        return RegimeStabilityResult(
            label="single_regime",
            dominant_regime=dom.regime,
            min_mean=dom.mean,
            max_mean=dom.mean,
            spread_ratio=0.0,
            per_regime=per,
            notes=f"only '{dom.regime}' has n>={min_per_regime}",
        )

    means = [s.mean for s in eligible]
    min_mean = min(means)
    max_mean = max(means)
    denom = max(abs(m) for m in means)
    spread = max_mean - min_mean
    spread_ratio = spread / denom if denom > 0 else 0.0

    same_sign = (min_mean >= 0 and max_mean >= 0) or (min_mean <= 0 and max_mean <= 0)
    dominant = max(eligible, key=lambda s: s.count)

    if not same_sign:
        return RegimeStabilityResult(
            label="unstable",
            dominant_regime=dominant.regime,
            min_mean=min_mean,
            max_mean=max_mean,
            spread_ratio=spread_ratio,
            per_regime=per,
            notes="regime means have opposite signs",
        )

    if spread_ratio > max_spread_ratio:
        return RegimeStabilityResult(
            label="unstable",
            dominant_regime=dominant.regime,
            min_mean=min_mean,
            max_mean=max_mean,
            spread_ratio=spread_ratio,
            per_regime=per,
            notes=(
                f"spread_ratio {spread_ratio:.4f} > cap {max_spread_ratio:.4f}"
            ),
        )

    return RegimeStabilityResult(
        label="stable",
        dominant_regime=dominant.regime,
        min_mean=min_mean,
        max_mean=max_mean,
        spread_ratio=spread_ratio,
        per_regime=per,
        notes="same sign and spread within cap",
    )


__all__ = [
    "CalendarRegime",
    "DEFAULT_BEAR_THRESHOLD",
    "DEFAULT_BULL_THRESHOLD",
    "DEFAULT_MAX_SPREAD_RATIO",
    "DEFAULT_MIN_REGIME_COUNT",
    "DEFAULT_TREND_LOOKBACK",
    "DEFAULT_VOL_LOOKBACK",
    "DEFAULT_VOL_QUANTILE",
    "RegimeStabilityResult",
    "RegimeSummary",
    "TrendRegime",
    "VolRegime",
    "assign_calendar_regime",
    "assign_calendar_regime_from_rows",
    "assign_trend_regime",
    "assign_volatility_regime",
    "classify_regime_stability",
    "summarize_by_regime",
]
