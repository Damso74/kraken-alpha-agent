"""Tests for :mod:`src.signals.volume_shock`."""

from __future__ import annotations

from src.signals.volume_shock import (
    EVENT_VARIANT_VOL_Z20,
    EVENT_VARIANT_VOL_Z20_QUIET,
    EVENT_VARIANT_VOL_Z20_RANGE,
    EVENT_VARIANT_VOL_Z60,
    VOLUME_Z_THRESHOLD,
    build_volume_shock_events,
    compute_volume_shock_features,
    is_blocked_by_event_rate,
)


def _candle(ts: int, vol: float, *, close: float = 100.0, spread: float = 2.0) -> dict:
    return {
        "timestamp": ts,
        "open": close,
        "high": close + spread / 2,
        "low": close - spread / 2,
        "close": close,
        "volume": vol,
    }


def test_empty_rows_returns_empty() -> None:
    assert build_volume_shock_events([]) == []
    assert compute_volume_shock_features([]) == []


def test_insufficient_history_returns_empty() -> None:
    base = 1_700_000_000
    rows = [_candle(base + i * 86_400, 100.0 + i) for i in range(30)]
    assert build_volume_shock_events(rows, variant=EVENT_VARIANT_VOL_Z60) == []


def test_features_include_registered_keys() -> None:
    base = 1_700_000_000
    rows = [_candle(base + i * 86_400, 100.0 + i * 0.1) for i in range(70)]
    feats = compute_volume_shock_features(rows)
    assert len(feats) == 70
    last = feats[-1]
    assert "volume_z_20" in last
    assert "volume_z_60" in last
    assert "range_compression_20" in last
    assert "return_abs_z_20" in last


def test_detects_volume_spike_z20() -> None:
    base = 1_700_100_000
    baseline_vols = [100.0 + i * 0.5 for i in range(30)]
    spike_vol = 50_000.0
    rows = [
        _candle(base + i * 86_400, vol)
        for i, vol in enumerate(baseline_vols + [spike_vol])
    ]
    events = build_volume_shock_events(rows, variant=EVENT_VARIANT_VOL_Z20)
    assert events
    assert events[-1] == rows[-1]["timestamp"]


def test_vol_z60_requires_longer_warmup() -> None:
    base = 1_700_200_000
    rows = [_candle(base + i * 86_400, 50.0 + i * 0.01) for i in range(70)]
    rows[-1] = _candle(base + 70 * 86_400, 1e7)
    events = build_volume_shock_events(rows, variant=EVENT_VARIANT_VOL_Z60)
    assert len(events) >= 1


def test_range_compression_variant_sparse_subset() -> None:
    base = 1_700_300_000
    rows: list[dict] = []
    for i in range(25):
        rows.append(_candle(base + i * 86_400, 80.0 + i, spread=1.0))
    rows.append(_candle(base + 25 * 86_400, 9000.0, spread=0.2))
    z20 = build_volume_shock_events(rows, variant=EVENT_VARIANT_VOL_Z20)
    combo = build_volume_shock_events(rows, variant=EVENT_VARIANT_VOL_Z20_RANGE)
    assert len(combo) <= len(z20)


def test_low_abs_return_variant() -> None:
    base = 1_700_400_000
    rows = [_candle(base + i * 86_400, 90.0 + i, close=100.0) for i in range(25)]
    rows.append(_candle(base + 25 * 86_400, 8000.0, close=100.01, spread=0.5))
    events = build_volume_shock_events(rows, variant=EVENT_VARIANT_VOL_Z20_QUIET)
    assert isinstance(events, list)


def test_unknown_variant_raises() -> None:
    try:
        build_volume_shock_events([], variant="invalid")  # type: ignore[arg-type]
    except ValueError as exc:
        assert "variant" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")


def test_g2_event_rate_cap() -> None:
    assert is_blocked_by_event_rate(31, 100)
    assert not is_blocked_by_event_rate(10, 100)


def test_compatible_with_event_study() -> None:
    from src.research.event_study import EventStudyWindow, run_event_study

    base = 1_700_500_000
    candles = [
        _candle(base + i * 86_400, 100.0 + i, close=100.0 + i * 0.2)
        for i in range(80)
    ]
    candles[-1] = _candle(base + 79 * 86_400, 50_000.0, close=120.0)
    events = build_volume_shock_events(
        candles, variant=EVENT_VARIANT_VOL_Z20, z_threshold=VOLUME_Z_THRESHOLD
    )
    if events:
        result = run_event_study(
            candles,
            events,
            [EventStudyWindow("post_3", 1, 3)],
            metrics=["return", "max_drawdown"],
        )
        assert result.events_count >= 1
