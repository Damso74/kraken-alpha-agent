"""Internal rolling statistics helpers for signal modules (stdlib only)."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any


def extract_timestamp(row: Mapping[str, Any]) -> int | None:
    val = row.get("timestamp")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def extract_float(row: Mapping[str, Any], key: str) -> float | None:
    val = row.get(key)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def sort_rows_by_timestamp(
    rows: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Return rows with valid timestamps, sorted ascending."""
    cleaned: list[tuple[int, Mapping[str, Any]]] = []
    for row in rows:
        ts = extract_timestamp(row)
        if ts is not None:
            cleaned.append((ts, row))
    cleaned.sort(key=lambda x: x[0])
    return [row for _, row in cleaned]


def rolling_z_scores(
    values: Sequence[float],
    lookback: int,
    *,
    min_periods: int | None = None,
) -> list[float | None]:
    """Rolling z-score of each point vs the prior ``lookback`` observations.

    For index ``i``, the reference window is ``values[i - lookback : i]``
    (the current value is excluded). Returns ``None`` where the window is
    too short or has zero variance.

    Parameters
    ----------
    values:
        Numeric series (need not be sorted — caller orders rows first).
    lookback:
        Number of prior points in the reference window.
    min_periods:
        Minimum window length required (defaults to ``lookback``).
    """
    if lookback < 2:
        return [None for _ in values]
    need = min_periods if min_periods is not None else lookback
    need = max(2, min(need, lookback))
    out: list[float | None] = []
    for i, current in enumerate(values):
        start = max(0, i - lookback)
        window = [float(v) for v in values[start:i]]
        if len(window) < need:
            out.append(None)
            continue
        try:
            mean = statistics.mean(window)
            stdev = statistics.stdev(window)
        except statistics.StatisticsError:
            out.append(None)
            continue
        if stdev <= 0:
            out.append(None)
            continue
        z = (float(current) - mean) / stdev
        if not math.isfinite(z):
            out.append(None)
        else:
            out.append(z)
    return out


def events_from_z_threshold(
    rows: Sequence[Mapping[str, Any]],
    z_scores: Sequence[float | None],
    *,
    z_threshold: float,
    direction: str = "high",
) -> list[int]:
    """Map z-score series back to event timestamps.

    ``direction`` is ``"high"`` (z > threshold), ``"low"`` (z < -threshold),
    or ``"abs"`` (|z| > threshold).
    """
    if len(rows) != len(z_scores):
        raise ValueError("rows and z_scores must have the same length")
    events: list[int] = []
    seen: set[int] = set()
    for row, z in zip(rows, z_scores, strict=True):
        if z is None:
            continue
        fire = False
        if direction == "high":
            fire = z > z_threshold
        elif direction == "low":
            fire = z < -z_threshold
        elif direction == "abs":
            fire = abs(z) > z_threshold
        else:
            raise ValueError(f"unknown direction {direction!r}")
        if not fire:
            continue
        ts = extract_timestamp(row)
        if ts is not None and ts not in seen:
            seen.add(ts)
            events.append(ts)
    return events
