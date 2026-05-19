"""Tests for :mod:`src.signals.eth_gas_congestion`."""

from __future__ import annotations

from src.signals.eth_gas_congestion import build_eth_gas_congestion_events


def _row(ts: int, fast_gwei: float) -> dict:
    return {"timestamp": ts, "fast_gwei": fast_gwei}


def test_empty_returns_empty() -> None:
    assert build_eth_gas_congestion_events([]) == []


def test_insufficient_data() -> None:
    rows = [_row(1_700_000_000 + i * 300, 20.0) for i in range(5)]
    assert build_eth_gas_congestion_events(rows, lookback=180) == []


def test_detects_gas_spike() -> None:
    base_ts = 1_700_000_000
    baseline = [25.0 + i * 0.1 for i in range(25)]
    spike = [200.0]
    rows = [
        _row(base_ts + i * 300, g)
        for i, g in enumerate(baseline + spike)
    ]
    events = build_eth_gas_congestion_events(
        rows, z_threshold=1.5, lookback=20
    )
    assert events
    assert events[-1] == rows[-1]["timestamp"]


def test_ignores_negative_gwei() -> None:
    rows = [_row(1_700_000_000 + i * 300, -1.0) for i in range(30)]
    assert build_eth_gas_congestion_events(rows, lookback=10) == []
