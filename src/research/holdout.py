"""Temporal hold-out utilities for G4 out-of-sample checks (research-only).

Pure functions — no network I/O. See ``docs/PAPER_OBSERVATION_DESIGN.md`` (G4)
and ``docs/SIGNAL_REJECTION_POLICY.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.research.event_study import EventStudyWindow, run_event_study
from src.research.placebo import benjamini_hochberg, empirical_p_value

DEFAULT_HOLDOUT_FRACTION = 0.30
MIN_TRAIN_CANDLES = 60
MIN_TEST_CANDLES = 30
DEFAULT_ALPHA = 0.05


@dataclass(frozen=True)
class HoldoutSplit:
    """Chronological train / test partition on sorted daily candles."""

    train_candles: tuple[dict[str, Any], ...]
    test_candles: tuple[dict[str, Any], ...]
    train_fraction: float
    split_timestamp: int | None

    @property
    def n_train(self) -> int:
        return len(self.train_candles)

    @property
    def n_test(self) -> int:
        return len(self.test_candles)


@dataclass(frozen=True)
class HoldoutCellResult:
    metric: str
    window: str
    train_mean: float | None
    train_p: float | None
    test_mean: float | None
    test_p: float | None
    train_bh_rejected: bool
    test_bh_rejected: bool


@dataclass(frozen=True)
class HoldoutEvaluation:
    split: HoldoutSplit
    train_events: int
    test_events: int
    cells: tuple[HoldoutCellResult, ...]
    oos_survives: bool
    failure_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
          "holdout_fraction": self.split.train_fraction,
          "split_timestamp": self.split.split_timestamp,
          "n_train_candles": self.split.n_train,
          "n_test_candles": self.split.n_test,
          "train_events": self.train_events,
          "test_events": self.test_events,
          "oos_survives": self.oos_survives,
          "failure_reason": self.failure_reason,
          "cells": [
              {
                  "metric": c.metric,
                  "window": c.window,
                  "train_mean": c.train_mean,
                  "train_p": c.train_p,
                  "test_mean": c.test_mean,
                  "test_p": c.test_p,
                  "train_bh_rejected": c.train_bh_rejected,
                  "test_bh_rejected": c.test_bh_rejected,
              }
              for c in self.cells
          ],
        }


def split_candles_holdout(
    candles: Sequence[Mapping[str, Any]],
    *,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    min_train: int = MIN_TRAIN_CANDLES,
    min_test: int = MIN_TEST_CANDLES,
) -> HoldoutSplit:
    """Split sorted candles: earliest ``1 - holdout_fraction`` = train, tail = test."""
    if not 0.0 < holdout_fraction < 1.0:
        raise ValueError(f"holdout_fraction must be in (0, 1), got {holdout_fraction}")
    ordered = sorted(candles, key=lambda c: int(c["timestamp"]))
    n = len(ordered)
    if n == 0:
        return HoldoutSplit((), (), holdout_fraction, None)

    test_n = max(min_test, int(round(n * holdout_fraction)))
    test_n = min(test_n, n - min_train) if n > min_train else 0
    if test_n <= 0:
        train = tuple(dict(c) for c in ordered)
        return HoldoutSplit(train, (), 1.0 - holdout_fraction, None)

    split_idx = n - test_n
    train = tuple(dict(c) for c in ordered[:split_idx])
    test = tuple(dict(c) for c in ordered[split_idx:])
    split_ts = int(test[0]["timestamp"]) if test else None
    actual_frac = len(test) / n
    return HoldoutSplit(train, test, actual_frac, split_ts)


def filter_events_to_candles(
    events: Sequence[int],
    candles: Sequence[Mapping[str, Any]],
) -> list[int]:
    """Keep events whose timestamp exists in ``candles``."""
    allowed = {int(c["timestamp"]) for c in candles}
    return sorted({int(e) for e in events if int(e) in allowed})


def _cell_p_values(
    candles: Sequence[Mapping[str, Any]],
    events: Sequence[int],
    *,
    metrics: Sequence[str],
    windows: Sequence[EventStudyWindow],
    n_placebos: int,
    seed: int,
    alpha: float,
    placebo_builder,
) -> dict[tuple[str, str], tuple[float, float, bool]]:
    """Return {(metric, window): (mean, p, bh_rejected)} for one partition."""
    if not events:
        return {}

    result = run_event_study(
        list(candles),
        events=list(events),
        windows=list(windows),
        metrics=list(metrics),
        compute_baseline=True,
    )
    candle_ts = [int(c["timestamp"]) for c in candles]
    out: dict[tuple[str, str], tuple[float, float, bool]] = {}
    p_values: list[float] = []
    keys: list[tuple[str, str]] = []

    for metric in metrics:
        for window in windows:
            row = result.row(metric, window.label)
            if row is None or row.n_events == 0:
                continue
            placebo_values: list[float] = []
            for i in range(n_placebos):
                placebo_events = placebo_builder(candle_ts, row.n_events, int(seed) + i)
                if not placebo_events:
                    continue
                pr = run_event_study(
                    list(candles),
                    events=placebo_events,
                    windows=[window],
                    metrics=[metric],
                    compute_baseline=False,
                )
                prow = pr.row(metric, window.label)
                if prow is not None and prow.n_events > 0:
                    placebo_values.append(float(prow.mean))
            if not placebo_values:
                continue
            p = empirical_p_value(observed=row.mean, placebo_values=placebo_values).two_sided
            key = (metric, window.label)
            keys.append(key)
            p_values.append(p)
            out[key] = (float(row.mean), float(p), False)

    if p_values:
        bh = benjamini_hochberg(p_values, alpha=alpha)
        for key, rejected in zip(keys, bh.rejected, strict=True):
            mean, p, _ = out[key]
            out[key] = (mean, p, bool(rejected))

    return out


def evaluate_holdout_g4(
    candles: Sequence[Mapping[str, Any]],
    events: Sequence[int],
    *,
    metrics: Sequence[str],
    windows: Sequence[EventStudyWindow],
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    n_placebos: int = 200,
    seed: int = 20260519,
    alpha: float = DEFAULT_ALPHA,
    reference_metric: str = "return",
    reference_window: str = "post_7",
) -> HoldoutEvaluation:
    """G4: BH or empirical p < alpha on **test** partition for reference cell."""
    split = split_candles_holdout(candles, holdout_fraction=holdout_fraction)
    train_events = filter_events_to_candles(events, split.train_candles)
    test_events = filter_events_to_candles(events, split.test_candles)

    if split.n_test < MIN_TEST_CANDLES:
        return HoldoutEvaluation(
            split=split,
            train_events=len(train_events),
            test_events=len(test_events),
            cells=(),
            oos_survives=False,
            failure_reason="ELIG_G4_FAIL_OOS: test window too short",
        )

    def uniform_placebo(pool: list[int], n_events: int, sub_seed: int) -> list[int]:
        from src.research.placebo import random_events_from_candles

        return random_events_from_candles(pool, n_events=n_events, seed=sub_seed)

    train_cells = _cell_p_values(
        split.train_candles,
        train_events,
        metrics=metrics,
        windows=windows,
        n_placebos=n_placebos,
        seed=seed,
        alpha=alpha,
        placebo_builder=uniform_placebo,
    )
    test_cells = _cell_p_values(
        split.test_candles,
        test_events,
        metrics=metrics,
        windows=windows,
        n_placebos=n_placebos,
        seed=seed + 100_000,
        alpha=alpha,
        placebo_builder=uniform_placebo,
    )

    merged: list[HoldoutCellResult] = []
    all_keys = sorted(set(train_cells) | set(test_cells))
    ref_train_bh = ref_test_bh = ref_test_p = None
    for key in all_keys:
        tr = train_cells.get(key)
        te = test_cells.get(key)
        cell = HoldoutCellResult(
            metric=key[0],
            window=key[1],
            train_mean=tr[0] if tr else None,
            train_p=tr[1] if tr else None,
            test_mean=te[0] if te else None,
            test_p=te[1] if te else None,
            train_bh_rejected=tr[2] if tr else False,
            test_bh_rejected=te[2] if te else False,
        )
        merged.append(cell)
        if key == (reference_metric, reference_window) and te:
            ref_train_bh = tr[2] if tr else False
            ref_test_bh = te[2]
            ref_test_p = te[1]

    survives = False
    reason: str | None = None
    if len(test_events) < 5:
        reason = "ELIG_G4_FAIL_OOS: fewer than 5 test events"
    elif ref_test_bh:
        survives = True
    elif ref_test_p is not None and ref_test_p < alpha:
        survives = True
    else:
        reason = (
            "ELIG_G4_FAIL_OOS: reference cell not significant on hold-out "
            f"({reference_metric}/{reference_window})"
        )
        if ref_train_bh and not ref_test_bh:
            reason += " (in-sample BH only)"

    return HoldoutEvaluation(
        split=split,
        train_events=len(train_events),
        test_events=len(test_events),
        cells=tuple(merged),
        oos_survives=survives,
        failure_reason=reason,
    )
