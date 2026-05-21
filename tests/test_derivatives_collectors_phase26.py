"""Phase 26A — derivatives collectors (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.data.collectors.binance_derivatives_public import (
    LIQUIDATIONS_STATUS,
    audit_derivatives_readiness,
    default_funding_cache_path,
    default_oi_cache_path,
    fetch_funding_rate_history,
    fetch_open_interest_history,
    parse_funding_rows,
    parse_oi_rows,
    save_funding_cache,
    save_oi_cache,
    load_derivatives_cache,
)


def _fake_fetcher(url: str, params: dict) -> list:
    if "fundingRate" in url:
        # Single page (< limit) to avoid pagination loop in tests.
        return [
            {
                "symbol": params["symbol"],
                "fundingRate": "0.0001",
                "fundingTime": 1_700_000_000_000,
            },
        ]
    return [
        {
            "symbol": params["symbol"],
            "sumOpenInterest": "1000.5",
            "timestamp": 1_700_000_000_000,
        }
    ]


def test_parse_funding_rows_dedupes() -> None:
    rows = parse_funding_rows(
        [
            {"fundingTime": 1000, "fundingRate": "0.01"},
            {"fundingTime": 1000, "fundingRate": "0.02"},
            {"fundingTime": 2000, "fundingRate": "-0.01"},
        ]
    )
    assert len(rows) == 2
    assert rows[0]["timestamp"] == 1000


def test_fetch_funding_hermetic(tmp_path: Path) -> None:
    rows = fetch_funding_rate_history("BTC", fetcher=_fake_fetcher)
    assert len(rows) >= 1
    assert "funding_rate" in rows[0]


def test_save_load_funding_cache(tmp_path: Path) -> None:
    path = tmp_path / "funding_BTC.json"
    save_funding_cache(
        path,
        ticker="BTC",
        rows=[{"fundingTime": 1700000000, "fundingRate": "0.0001"}],
    )
    loaded, meta = load_derivatives_cache(path)
    assert len(loaded) == 1
    assert meta.get("status") == "available"


def test_save_load_oi_cache(tmp_path: Path) -> None:
    path = tmp_path / "oi_ETH_4h.json"
    save_oi_cache(
        path,
        ticker="ETH",
        period="4h",
        rows=[{"timestamp": 1700000000, "sumOpenInterest": "500"}],
    )
    loaded, _ = load_derivatives_cache(path)
    assert loaded[0]["open_interest"] == 500.0


def test_audit_readiness_blocked_without_cache(tmp_path: Path) -> None:
    manifest = audit_derivatives_readiness(["BTC"], cache_dir=tmp_path, min_funding_rows=10)
    liq = next(e for e in manifest["entries"] if e["series"] == "liquidations")
    assert liq["status"] == LIQUIDATIONS_STATUS


def test_audit_readiness_ok_with_seed(tmp_path: Path) -> None:
    save_funding_cache(
        default_funding_cache_path("BTC", tmp_path),
        ticker="BTC",
        rows=[
            {"fundingTime": 1_600_000_000 + i * 28800, "fundingRate": "0.0001"}
            for i in range(120)
        ],
    )
    save_oi_cache(
        default_oi_cache_path("BTC", "4h", tmp_path),
        ticker="BTC",
        period="4h",
        rows=[
            {"timestamp": 1_600_000_000 + i * 14400, "sumOpenInterest": str(1000 + i)}
            for i in range(120)
        ],
    )
    manifest = audit_derivatives_readiness(["BTC"], cache_dir=tmp_path, min_funding_rows=100)
    funding = next(e for e in manifest["entries"] if e["series"] == "funding")
    assert funding["status"] == "available"
