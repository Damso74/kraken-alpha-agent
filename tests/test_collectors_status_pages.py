"""Hermetic tests for :mod:`src.data.collectors.status_pages`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.collectors.status_pages import (
    CollectorError,
    fetch_all_status_incidents,
    fetch_status_incidents,
    parse_statuspage_incidents,
)


INCIDENTS_FIXTURE = {
    "incidents": [
        {
            "id": "inc1",
            "name": "API latency",
            "status": "investigating",
            "impact": "minor",
            "created_at": "2026-05-17T10:00:00Z",
            "updated_at": "2026-05-17T11:00:00Z",
        },
        {
            "id": "inc2",
            "name": "Resolved issue",
            "status": "resolved",
            "impact": "major",
            "created_at": "2026-05-16T08:00:00Z",
            "updated_at": "2026-05-16T12:00:00Z",
        },
        {"id": ""},  # skipped
    ]
}


def test_parse_statuspage_incidents() -> None:
    rows = parse_statuspage_incidents(INCIDENTS_FIXTURE, venue="kraken")
    assert len(rows) == 2
    by_id = {r["incident_id"]: r for r in rows}
    assert by_id["inc1"]["venue"] == "kraken"
    assert by_id["inc1"]["impact"] == "minor"
    assert isinstance(by_id["inc1"]["timestamp"], int)
    assert by_id["inc2"]["status"] == "resolved"
    assert rows[0]["timestamp"] <= rows[1]["timestamp"]


def test_parse_statuspage_incidents_bad_payload() -> None:
    with pytest.raises(CollectorError):
        parse_statuspage_incidents([], venue="kraken")


def test_fetch_status_incidents_injects_fetcher(tmp_path: Path) -> None:
    def fake_fetcher(venue: str) -> dict:
        assert venue == "kraken"
        return INCIDENTS_FIXTURE

    rows = fetch_status_incidents("kraken", fetcher=fake_fetcher)
    assert len(rows) == 2


def test_fetch_status_incidents_unknown_venue() -> None:
    with pytest.raises(ValueError):
        fetch_status_incidents("binance")


def test_fetch_all_status_incidents_merges(tmp_path: Path) -> None:
    def fake_fetcher(venue: str) -> dict:
        payload = dict(INCIDENTS_FIXTURE)
        payload["incidents"] = [dict(INCIDENTS_FIXTURE["incidents"][0])]
        payload["incidents"][0]["id"] = f"{venue}-1"
        return payload

    rows = fetch_all_status_incidents(fetcher=fake_fetcher)
    assert len(rows) == 2
    venues = {r["venue"] for r in rows}
    assert venues == {"kraken", "coinbase"}


def test_fetch_status_incidents_reads_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "status.json"
    parsed = parse_statuspage_incidents(INCIDENTS_FIXTURE, venue="kraken")
    cache_path.write_text(
        json.dumps({"entries": {"incidents_kraken": parsed}}),
        encoding="utf-8",
    )

    def explode(_venue: str) -> dict:
        raise AssertionError("fetcher must not run when cache populated")

    rows = fetch_status_incidents("kraken", cache_path=cache_path, fetcher=explode)
    assert len(rows) == 2
