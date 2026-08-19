"""Stablecoin aggregate supply shock events (7d / 30d change z-score).

Row shape
---------
Each row is a mapping with:

- ``timestamp`` (int): unix seconds UTC
- ``total_mcap`` (float): aggregate stablecoin market cap in USD
- ``supply_chg_7d`` / ``supply_chg_30d`` (float, optional): pre-computed
  fractional change; when absent, computed from ``total_mcap`` on the
  sorted series.

Hypothesis
----------
Abnormally fast stablecoin supply expansion (liquidity injection) may
precede risk-on crypto moves; contraction may precede deleveraging.

Phase 11 pre-registration (frozen — no grid search)
---------------------------------------------------
Only these four thresholds are authorised for P9-SC-001-PR:

- ``supply_change_7d`` z >= 1.0  (expansion)
- ``supply_change_30d`` z >= 1.0 (expansion)
- ``supply_change_7d`` z <= -1.0 (contraction)
- ``supply_change_30d`` z <= -1.0 (contraction)

Overfit risk
------------
Regime-dependent — 2020–2021 bull cycles dominated by supply growth;
thresholds tuned on one era may not generalise.

Rejection condition
-------------------
Drop the signal when placebo event studies on random timestamps show
post-event returns indistinguishable from baseline (see
:mod:`src.research.placebo`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._stats import (
    events_from_z_threshold,
    extract_float,
    extract_timestamp,
    rolling_z_scores,
    sort_rows_by_timestamp,
)

# Phase 11 frozen thresholds — do not grid-search beyond this tuple.
PREREGISTERED_THRESHOLDS: tuple[dict[str, Any], ...] = (
    {
        "preregistration_id": "P9-SC-001-PR-7d-high",
        "metric": "supply_change_7d",
        "supply_lag": 7,
        "z_threshold": 1.0,
        "direction": "high",
    },
    {
        "preregistration_id": "P9-SC-001-PR-30d-high",
        "metric": "supply_change_30d",
        "supply_lag": 30,
        "z_threshold": 1.0,
        "direction": "high",
    },
    {
        "preregistration_id": "P9-SC-001-PR-7d-low",
        "metric": "supply_change_7d",
        "supply_lag": 7,
        "z_threshold": 1.0,
        "direction": "low",
    },
    {
        "preregistration_id": "P9-SC-001-PR-30d-low",
        "metric": "supply_change_30d",
        "supply_lag": 30,
        "z_threshold": 1.0,
        "direction": "low",
    },
)

_SUPPLY_CHG_FIELD = {7: "supply_chg_7d", 30: "supply_chg_30d"}


@dataclass(frozen=True)
class StablecoinThresholdSpec:
    """One pre-registered Phase 11 stablecoin supply threshold."""

    preregistration_id: str
    metric: str
    supply_lag: int
    z_threshold: float
    direction: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> StablecoinThresholdSpec:
        return cls(
            preregistration_id=str(data["preregistration_id"]),
            metric=str(data["metric"]),
            supply_lag=int(data["supply_lag"]),
            z_threshold=float(data["z_threshold"]),
            direction=str(data["direction"]),
        )


def preregistered_threshold_specs() -> tuple[StablecoinThresholdSpec, ...]:
    """Return frozen Phase 11 threshold specs (no grid search)."""
    return tuple(
        StablecoinThresholdSpec.from_mapping(t) for t in PREREGISTERED_THRESHOLDS
    )


def _precomputed_change_key(lag: int) -> str:
    if lag in _SUPPLY_CHG_FIELD:
        return _SUPPLY_CHG_FIELD[lag]
    return f"supply_chg_{lag}d"


def _supply_change_series(
    rows: Sequence[Mapping[str, Any]],
    *,
    lag: int = 7,
) -> list[float]:
    """Build ``lag``-day fractional supply change aligned with ``rows``."""
    field = _precomputed_change_key(lag)
    changes: list[float] = []
    mcaps: list[float] = []
    for row in rows:
        precomputed = extract_float(row, field)
        if precomputed is None and lag not in _SUPPLY_CHG_FIELD:
            precomputed = extract_float(row, "supply_chg_7d")
        mcap = extract_float(row, "total_mcap")
        mcaps.append(mcap if mcap is not None else float("nan"))
        if precomputed is not None:
            changes.append(precomputed)
        else:
            changes.append(float("nan"))

    for i in range(len(rows)):
        if not math.isnan(changes[i]):
            continue
        if i < lag:
            continue
        prev = mcaps[i - lag]
        cur = mcaps[i]
        if math.isnan(prev) or math.isnan(cur) or prev <= 0:
            continue
        changes[i] = (cur - prev) / prev

    return changes


def build_stablecoin_supply_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    z_threshold: float = 1.5,
    lookback: int = 180,
    lag: int = 7,
    direction: str = "high",
) -> list[int]:
    """Emit timestamps when supply change z-score exceeds ``z_threshold``.

    Parameters
    ----------
    rows:
        Stablecoin aggregate feed rows (see module docstring).
    z_threshold:
        Minimum |z| tail to flag an event (default 1.5; Phase 11 uses 1.0).
    lookback:
        Rolling reference window length in observations (default 180).
    lag:
        Days/steps for supply change when not pre-computed (7 or 30).
    direction:
        ``"high"`` — expansion shock; ``"low"`` — contraction shock;
        ``"abs"`` — either tail.

    Returns
    -------
    list[int]
        Unix UTC timestamps, ascending, deduplicated. Empty when data are
        insufficient (fewer than ``lookback + lag + 1`` usable points).
    """
    if lookback < 2:
        return []
    sorted_rows = sort_rows_by_timestamp(rows)
    if not sorted_rows:
        return []

    changes = _supply_change_series(sorted_rows, lag=lag)
    values: list[float] = []
    scored_rows: list[Mapping[str, Any]] = []
    for row, chg in zip(sorted_rows, changes, strict=True):
        if math.isnan(chg) or extract_timestamp(row) is None:
            continue
        values.append(chg)
        scored_rows.append(row)

    if len(values) < lookback + 1:
        return []

    z_scores = rolling_z_scores(values, lookback)
    return events_from_z_threshold(
        scored_rows, z_scores, z_threshold=z_threshold, direction=direction
    )


def build_preregistered_stablecoin_events(
    rows: Sequence[Mapping[str, Any]],
    spec: StablecoinThresholdSpec | Mapping[str, Any],
    *,
    lookback: int = 180,
) -> list[int]:
    """Build events for one frozen Phase 11 threshold spec."""
    if not isinstance(spec, StablecoinThresholdSpec):
        spec = StablecoinThresholdSpec.from_mapping(spec)
    return build_stablecoin_supply_events(
        rows,
        z_threshold=spec.z_threshold,
        lookback=lookback,
        lag=spec.supply_lag,
        direction=spec.direction,
    )


__all__ = [
    "PREREGISTERED_THRESHOLDS",
    "StablecoinThresholdSpec",
    "build_preregistered_stablecoin_events",
    "build_stablecoin_supply_events",
    "preregistered_threshold_specs",
]
