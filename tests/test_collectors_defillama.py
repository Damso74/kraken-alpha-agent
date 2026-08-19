"""Hermetic tests for :mod:`src.data.collectors.defillama`."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.data.collectors.defillama import (
    CollectorError,
    fetch_chain_tvl,
    fetch_stablecoin_supply,
    parse_chain_tvl,
    parse_stablecoin_charts,
)


def _ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


STABLECOIN_FIXTURE = [
    {
        "date": _ts(date(2026, 5, 17)),
        "totalCirculating": {"peggedUSD": 150_000_000_000},
    },
    {
        "date": _ts(date(2026, 5, 18)),
        "totalCirculatingUSD": 151_000_000_000,
    },
    {"date": "not-a-ts"},  # dropped
]

CHAIN_TVL_FIXTURE = [
    {"date": _ts(date(2026, 5, 17)), "tvl": 50_000_000_000},
    {"date": _ts(date(2026, 5, 18)), "tvl": 51_000_000_000},
]


def test_parse_stablecoin_charts_normalizes_rows() -> None:
    rows = parse_stablecoin_charts(STABLECOIN_FIXTURE)
    assert len(rows) == 2
    assert rows[0]["source"] == "defillama_stablecoins"
    assert rows[0]["date"] == "2026-05-17"
    assert rows[0]["total_circulating_usd"] == 150_000_000_000
    assert rows[1]["total_circulating_usd"] == 151_000_000_000
    assert rows[1]["timestamp"] - rows[0]["timestamp"] == 86400


def test_parse_stablecoin_charts_rejects_non_list() -> None:
    with pytest.raises(CollectorError):
        parse_stablecoin_charts({})


def test_parse_chain_tvl_includes_chain_label() -> None:
    rows = parse_chain_tvl(CHAIN_TVL_FIXTURE, chain="Ethereum")
    assert len(rows) == 2
    assert rows[0]["chain"] == "Ethereum"
    assert rows[0]["tvl_usd"] == 50_000_000_000


def test_fetch_stablecoin_supply_cache_hit_skips_fetcher(tmp_path: Path) -> None:
    cache_path = tmp_path / "defi.json"
    parsed = parse_stablecoin_charts(STABLECOIN_FIXTURE)
    cache_path.write_text(
        json.dumps({"entries": {"stablecoin_supply": parsed}}),
        encoding="utf-8",
    )

    def explode() -> list:
        raise AssertionError("fetcher must not run on cache hit")

    rows = fetch_stablecoin_supply(
        "2026-05-17",
        "2026-05-18",
        cache_path=cache_path,
        fetcher=explode,
    )
    assert len(rows) == 2


def test_fetch_stablecoin_supply_cache_miss_persists(tmp_path: Path) -> None:
    cache_path = tmp_path / "defi.json"

    def fake_fetcher() -> list:
        return STABLECOIN_FIXTURE

    rows = fetch_stablecoin_supply(
        "2026-05-17",
        "2026-05-18",
        cache_path=cache_path,
        fetcher=fake_fetcher,
    )
    assert len(rows) == 2
    assert cache_path.exists()
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "stablecoin_supply" in cached["entries"]


def test_fetch_chain_tvl_filters_window() -> None:
    def fake_fetcher(_chain: str) -> list:
        return CHAIN_TVL_FIXTURE

    rows = fetch_chain_tvl(
        "Ethereum",
        "2026-05-18",
        "2026-05-18",
        fetcher=fake_fetcher,
    )
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-05-18"
