"""Tests for :mod:`src.signals.stablecoin_supply`."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.signals.stablecoin_supply import (
    PREREGISTERED_THRESHOLDS,
    StablecoinThresholdSpec,
    build_preregistered_stablecoin_events,
    build_stablecoin_supply_events,
    preregistered_threshold_specs,
)


def _row(ts: int, chg: float) -> dict:
    return {"timestamp": ts, "total_mcap": 100.0, "supply_chg_7d": chg}


def test_empty_rows_returns_empty() -> None:
    assert build_stablecoin_supply_events([]) == []


def test_insufficient_data_returns_empty() -> None:
    rows = [_row(1_700_000_000 + i * 86_400, 0.01) for i in range(10)]
    assert build_stablecoin_supply_events(rows, lookback=180) == []


def test_detects_supply_expansion_spike() -> None:
    base_ts = 1_700_000_000
    baseline = [0.01 + i * 0.0001 for i in range(25)]
    spike = [0.50]
    rows = [
        _row(base_ts + i * 86_400, chg)
        for i, chg in enumerate(baseline + spike)
    ]
    events = build_stablecoin_supply_events(
        rows, z_threshold=1.5, lookback=20, lag=7
    )
    assert events
    assert events[-1] == rows[-1]["timestamp"]


def test_low_direction_flags_contraction() -> None:
    base_ts = 1_700_100_000
    baseline = [0.01 + i * 0.0001 for i in range(25)]
    dip = [-0.40]
    rows = [
        _row(base_ts + i * 86_400, chg)
        for i, chg in enumerate(baseline + dip)
    ]
    events = build_stablecoin_supply_events(
        rows, z_threshold=1.5, lookback=20, direction="low"
    )
    assert len(events) == 1


def test_derives_change_from_mcap_when_field_missing() -> None:
    base_ts = 1_700_200_000
    mcaps = [100.0 + i * 0.01 for i in range(28)] + [150.0]
    rows = [
        {"timestamp": base_ts + i * 86_400, "total_mcap": m}
        for i, m in enumerate(mcaps)
    ]
    events = build_stablecoin_supply_events(rows, lookback=20, lag=7)
    assert events


def test_30d_lag_detects_spike_from_mcap() -> None:
    base_ts = 1_700_300_000
    mcaps = [100.0 + i * 0.01 for i in range(50)] + [180.0]
    rows = [
        {"timestamp": base_ts + i * 86_400, "total_mcap": m}
        for i, m in enumerate(mcaps)
    ]
    events = build_stablecoin_supply_events(
        rows, z_threshold=1.0, lookback=20, lag=30, direction="high"
    )
    assert events


def test_preregistered_thresholds_frozen_tuple() -> None:
    specs = preregistered_threshold_specs()
    assert len(specs) == 4
    assert len(PREREGISTERED_THRESHOLDS) == 4
    metrics = {s.metric for s in specs}
    assert metrics == {"supply_change_7d", "supply_change_30d"}
    for spec in specs:
        assert spec.z_threshold == 1.0
        assert spec.direction in ("high", "low")


def test_build_preregistered_events_matches_manual_call() -> None:
    base_ts = 1_700_400_000
    rows = [_row(base_ts + i * 86_400, 0.01 + i * 0.0001) for i in range(26)]
    rows.append(_row(base_ts + 26 * 86_400, 0.55))
    spec = StablecoinThresholdSpec.from_mapping(PREREGISTERED_THRESHOLDS[0])
    manual = build_stablecoin_supply_events(
        rows,
        z_threshold=spec.z_threshold,
        lookback=20,
        lag=spec.supply_lag,
        direction=spec.direction,
    )
    prereg = build_preregistered_stablecoin_events(rows, spec, lookback=20)
    assert manual == prereg


def test_compatible_with_event_study() -> None:
    from src.research.event_study import EventStudyWindow, run_event_study

    candles = [
        {
            "timestamp": 1_700_000_000 + i * 3600,
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0 + i * 0.1,
            "volume": 1.0,
        }
        for i in range(50)
    ]
    events = build_stablecoin_supply_events(
        [_row(1_700_000_000 + i * 86_400, 0.01) for i in range(30)]
        + [_row(1_700_000_000 + 30 * 86_400, 0.9)],
        lookback=20,
    )
    if events:
        result = run_event_study(
            candles,
            events,
            [EventStudyWindow("post", 1, 3)],
            metrics=["return"],
        )
        assert result.events_count >= 1


@pytest.mark.parametrize(
    "n_events,bh_rejected,placebo_pass,expected",
    [
        (0, 0, False, "blocked: insufficient events"),
        (3, 1, True, "blocked: insufficient events"),
        (8, 0, True, "not supported"),
        (8, 1, False, "weak evidence"),
        (8, 2, True, "candidate for OOS testing (NOT tradable)"),
    ],
)
def test_compute_phase11_verdict(
    n_events: int,
    bh_rejected: int,
    placebo_pass: bool,
    expected: str,
) -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "event_study_stablecoins.py"
    spec = importlib.util.spec_from_file_location("event_study_stablecoins", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    verdict = mod.compute_phase11_verdict(
        n_events=n_events,
        bh_rejected=bh_rejected,
        placebo_pass=placebo_pass,
    )
    assert verdict == expected
