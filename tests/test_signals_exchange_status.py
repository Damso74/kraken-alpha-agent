"""Tests for :mod:`src.signals.exchange_status`."""

from __future__ import annotations

import pytest

from src.signals.exchange_status import (
    build_exchange_status_events,
    classify_incident_kind,
    incident_duration_minutes,
)


def _row(
    ts: int,
    impact: str,
    provider: str = "kraken",
    *,
    name: str = "API issue",
    started_at: str | None = None,
    updated_at: str | None = None,
) -> dict:
    out = {
        "timestamp": ts,
        "impact": impact,
        "component": "trading",
        "provider": provider,
        "name": name,
    }
    if started_at is not None:
        out["started_at"] = started_at
    if updated_at is not None:
        out["updated_at"] = updated_at
    return out


def test_empty_returns_empty() -> None:
    assert build_exchange_status_events([]) == []


def test_filters_by_min_impact() -> None:
    rows = [
        _row(100, "minor"),
        _row(200, "major"),
        _row(300, "critical"),
        _row(400, "none"),
    ]
    minor = build_exchange_status_events(rows, min_impact="minor")
    assert minor == [100, 200, 300]

    major = build_exchange_status_events(rows, min_impact="major")
    assert major == [200, 300]

    critical = build_exchange_status_events(rows, min_impact="critical")
    assert critical == [300]


def test_impact_exact_tier() -> None:
    rows = [
        _row(100, "minor"),
        _row(200, "major"),
        _row(300, "critical"),
    ]
    assert build_exchange_status_events(rows, impact_exact="major") == [200]


def test_deduplicates_same_timestamp() -> None:
    rows = [_row(500, "major"), _row(500, "critical")]
    assert build_exchange_status_events(rows) == [500]


def test_provider_filter() -> None:
    rows = [
        _row(100, "major", "kraken"),
        _row(200, "major", "coinbase"),
    ]
    events = build_exchange_status_events(
        rows, min_impact="minor", providers=["kraken"]
    )
    assert events == [100]


def test_incident_kind_scheduled_vs_unscheduled() -> None:
    rows = [
        _row(100, "minor", name="Scheduled maintenance window"),
        _row(200, "minor", name="API latency spike"),
    ]
    assert classify_incident_kind(rows[0]) == "scheduled"
    assert classify_incident_kind(rows[1]) == "unscheduled"
    assert build_exchange_status_events(rows, incident_kind="scheduled") == [100]
    assert build_exchange_status_events(rows, incident_kind="unscheduled") == [200]


def test_min_duration_minutes() -> None:
    rows = [
        _row(
            100,
            "minor",
            started_at="2026-05-01T10:00:00Z",
            updated_at="2026-05-01T10:15:00Z",
        ),
        _row(
            200,
            "minor",
            started_at="2026-05-01T10:00:00Z",
            updated_at="2026-05-01T11:00:00Z",
        ),
    ]
    events = build_exchange_status_events(rows, min_duration_minutes=30.0)
    assert events == [200]


def test_incident_duration_minutes() -> None:
    row = _row(
        1,
        "minor",
        started_at="2026-05-01T10:00:00Z",
        updated_at="2026-05-01T10:45:00Z",
    )
    assert incident_duration_minutes(row) == pytest.approx(45.0)


def test_invalid_min_impact_raises() -> None:
    with pytest.raises(ValueError):
        build_exchange_status_events([_row(1, "major")], min_impact="extreme")


def test_invalid_incident_kind_raises() -> None:
    with pytest.raises(ValueError):
        build_exchange_status_events([_row(1, "major")], incident_kind="maybe")  # type: ignore[arg-type]
