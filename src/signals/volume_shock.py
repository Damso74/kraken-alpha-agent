"""Daily OHLC volume-shock events (pre-registered Phase 11, P9-MS-023).

Row shape
---------
Each row is a mapping with:

- ``timestamp`` (int): unix seconds UTC
- ``open``, ``high``, ``low``, ``close``, ``volume`` (float)

Pre-registered features (no post-hoc tuning)
--------------------------------------------
- ``volume_z_20`` — rolling z-score of ``volume`` (lookback 20)
- ``volume_z_60`` — rolling z-score of ``volume`` (lookback 60)
- ``range_compression_20`` — z-score of ``(high - low) / close`` (lookback 20)
- ``return_abs_z_20`` — z-score of ``|close/prev_close - 1|`` (lookback 20)

Pre-registered event variants
-----------------------------
1. ``vol_z20_high`` — ``volume_z_20 >= 2.0``
2. ``vol_z60_high`` — ``volume_z_60 >= 2.0``
3. ``vol_z20_range_compression`` — ``volume_z_20 >= 2.0`` and range compression
   (``range_compression_20 <= -1.0``)
4. ``vol_z20_low_abs_return`` — ``volume_z_20 >= 2.0`` and quiet return
   (``return_abs_z_20 <= -1.0``)

Hypothesis
----------
Abnormally high daily volume may coincide with information arrival; combined
with tight range or flat return, a "squeeze then expansion" narrative is
testable at daily resolution only (not tradeable without OOS + costs).

Overfit risk
------------
Venue volume ≠ global volume; z-threshold and lookbacks are fixed a priori.

Rejection condition
-------------------
Discard when event rate exceeds ~30% of candles (G2 turnover), when shift
+30d placebos reproduce the same hit-rate, or when forward returns match
random-date placebos.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ._stats import (
    extract_float,
    extract_timestamp,
    rolling_z_scores,
    sort_rows_by_timestamp,
)

# Pre-registered constants (Phase 11 — do not optimize after results).
VOLUME_Z_THRESHOLD = 2.0
LOOKBACK_SHORT = 20
LOOKBACK_LONG = 60
RANGE_COMPRESSION_Z_MAX = -1.0
RETURN_ABS_Z_MAX = -1.0
MAX_EVENT_RATE_FRACTION = 0.30

EVENT_VARIANT_VOL_Z20 = "vol_z20_high"
EVENT_VARIANT_VOL_Z60 = "vol_z60_high"
EVENT_VARIANT_VOL_Z20_RANGE = "vol_z20_range_compression"
EVENT_VARIANT_VOL_Z20_QUIET = "vol_z20_low_abs_return"

EVENT_VARIANTS = (
    EVENT_VARIANT_VOL_Z20,
    EVENT_VARIANT_VOL_Z60,
    EVENT_VARIANT_VOL_Z20_RANGE,
    EVENT_VARIANT_VOL_Z20_QUIET,
)


def _hl_range_pct(row: Mapping[str, Any]) -> float | None:
    high = extract_float(row, "high")
    low = extract_float(row, "low")
    close = extract_float(row, "close")
    if high is None or low is None or close is None or close <= 0:
        return None
    if high < low:
        return None
    return (high - low) / close


def _abs_simple_return(
    row: Mapping[str, Any], prev_close: float | None
) -> float | None:
    close = extract_float(row, "close")
    if close is None or prev_close is None or prev_close <= 0:
        return None
    return abs(close / prev_close - 1.0)


def compute_volume_shock_features(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach pre-registered features to each valid OHLC row (sorted by time)."""
    sorted_rows = sort_rows_by_timestamp(rows)
    scored: list[Mapping[str, Any]] = []
    volumes: list[float] = []
    range_pcts: list[float] = []
    abs_returns: list[float] = []

    prev_close: float | None = None
    for row in sorted_rows:
        vol = extract_float(row, "volume")
        if vol is None or vol < 0:
            prev_close = extract_float(row, "close")
            continue
        rng = _hl_range_pct(row)
        if rng is None:
            prev_close = extract_float(row, "close")
            continue
        ar = _abs_simple_return(row, prev_close)
        prev_close = extract_float(row, "close")
        scored.append(row)
        volumes.append(vol)
        range_pcts.append(rng)
        abs_returns.append(ar if ar is not None else 0.0)

    if not scored:
        return []

    vol_z20 = rolling_z_scores(volumes, LOOKBACK_SHORT)
    vol_z60 = rolling_z_scores(volumes, LOOKBACK_LONG)
    range_z20 = rolling_z_scores(range_pcts, LOOKBACK_SHORT)
    abs_ret_z20 = rolling_z_scores(abs_returns, LOOKBACK_SHORT)

    out: list[dict[str, Any]] = []
    for i, (row, vz20, vz60, rz, az) in enumerate(
        zip(scored, vol_z20, vol_z60, range_z20, abs_ret_z20, strict=True)
    ):
        ts = extract_timestamp(row)
        if ts is None:
            continue
        out.append(
            {
                "timestamp": ts,
                "volume_z_20": vz20,
                "volume_z_60": vz60,
                "range_compression_20": rz,
                "return_abs_z_20": az,
                "volume": volumes[i],
            }
        )
    return out


def _events_from_features(
    features: Sequence[Mapping[str, Any]],
    *,
    variant: str,
    z_threshold: float = VOLUME_Z_THRESHOLD,
) -> list[int]:
    events: list[int] = []
    seen: set[int] = set()
    for row in features:
        ts = extract_timestamp(row)
        if ts is None:
            continue
        vz20 = row.get("volume_z_20")
        vz60 = row.get("volume_z_60")
        rz = row.get("range_compression_20")
        az = row.get("return_abs_z_20")
        fire = False
        if variant == EVENT_VARIANT_VOL_Z20:
            fire = vz20 is not None and float(vz20) >= z_threshold
        elif variant == EVENT_VARIANT_VOL_Z60:
            fire = vz60 is not None and float(vz60) >= z_threshold
        elif variant == EVENT_VARIANT_VOL_Z20_RANGE:
            fire = (
                vz20 is not None
                and float(vz20) >= z_threshold
                and rz is not None
                and float(rz) <= RANGE_COMPRESSION_Z_MAX
            )
        elif variant == EVENT_VARIANT_VOL_Z20_QUIET:
            fire = (
                vz20 is not None
                and float(vz20) >= z_threshold
                and az is not None
                and float(az) <= RETURN_ABS_Z_MAX
            )
        else:
            raise ValueError(f"unknown volume-shock variant {variant!r}")
        if fire and ts not in seen:
            seen.add(ts)
            events.append(ts)
    return events


def build_volume_shock_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    variant: str = EVENT_VARIANT_VOL_Z20,
    z_threshold: float = VOLUME_Z_THRESHOLD,
) -> list[int]:
    """Build event timestamps for a pre-registered volume-shock variant."""
    if variant not in EVENT_VARIANTS:
        raise ValueError(f"variant must be one of {EVENT_VARIANTS}, got {variant!r}")
    features = compute_volume_shock_features(rows)
    min_rows = (
        LOOKBACK_LONG + 1
        if variant == EVENT_VARIANT_VOL_Z60
        else LOOKBACK_SHORT + 1
    )
    if len(features) < min_rows:
        return []
    return _events_from_features(features, variant=variant, z_threshold=z_threshold)


def event_rate_fraction(n_events: int, n_candles: int) -> float:
    """Share of daily candles flagged as events (G2 guard)."""
    if n_candles <= 0:
        return 0.0
    return n_events / n_candles


def is_blocked_by_event_rate(n_events: int, n_candles: int) -> bool:
    """True when event rate exceeds the pre-registered G2 cap (~30%)."""
    return event_rate_fraction(n_events, n_candles) > MAX_EVENT_RATE_FRACTION


__all__ = [
    "VOLUME_Z_THRESHOLD",
    "LOOKBACK_SHORT",
    "LOOKBACK_LONG",
    "RANGE_COMPRESSION_Z_MAX",
    "RETURN_ABS_Z_MAX",
    "MAX_EVENT_RATE_FRACTION",
    "EVENT_VARIANT_VOL_Z20",
    "EVENT_VARIANT_VOL_Z60",
    "EVENT_VARIANT_VOL_Z20_RANGE",
    "EVENT_VARIANT_VOL_Z20_QUIET",
    "EVENT_VARIANTS",
    "compute_volume_shock_features",
    "build_volume_shock_events",
    "event_rate_fraction",
    "is_blocked_by_event_rate",
]
