from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.data.collectors._common import CollectorError
from src.data.collectors.binance_world_order_flow import (
    aggregate_aggtrades_zip,
    aggregate_daily_klines_to_weeks,
    append_universe_snapshot,
    compare_daily_flow_sources,
    compare_weekly_flow_sources,
    fetch_daily_aggtrades,
    fetch_daily_klines,
    fetch_dynamic_universe_week,
    fetch_monthly_aggtrades,
    load_universe_snapshots,
    parse_daily_klines,
    parse_exchange_info,
    universe_at,
)

MONDAY_MS = 1_704_067_200_000  # 2024-01-01 UTC


def _exchange_info(*bases: str) -> dict:
    return {
        "symbols": [
            {
                "symbol": f"{base}USDT",
                "baseAsset": base,
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
            }
            for base in bases
        ]
    }


def _kline(day: int, quote: float = 1_000.0, buy: float = 600.0) -> list:
    timestamp = MONDAY_MS + day * 86_400_000
    return [timestamp, "1", "1", "1", "1", "1", timestamp + 1, str(quote), 1, "1", str(buy)]


def _zip_csv(rows: list[list[str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        text = io.StringIO()
        writer = csv.writer(text, lineterminator="\n")
        writer.writerows(rows)
        archive.writestr("BTCUSDT-aggTrades-2024-01.csv", text.getvalue())
    return buffer.getvalue()


def test_exchange_info_snapshots_are_point_in_time_and_append_only(tmp_path: Path) -> None:
    first = parse_exchange_info(
        _exchange_info("BTC", "ETH"),
        observed_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    second = parse_exchange_info(
        _exchange_info("BTC", "ETH", "SOL"),
        observed_at=datetime(2024, 1, 8, tzinfo=UTC),
    )
    path = tmp_path / "universe.jsonl"
    append_universe_snapshot(path, first)
    append_universe_snapshot(path, second)
    loaded = load_universe_snapshots(path)
    assert [member.base_asset for member in universe_at(loaded, decision_timestamp=first.observed_at)] == ["BTC", "ETH"]
    with pytest.raises(CollectorError, match="no point-in-time"):
        universe_at(loaded, decision_timestamp=first.observed_at - 1)
    with pytest.raises(CollectorError, match="append-only"):
        append_universe_snapshot(path, first)


def test_daily_klines_parse_and_complete_week_aggregation() -> None:
    rows = parse_daily_klines(
        [_kline(day) for day in range(7)], symbol="BTCUSDT", base_asset="BTC"
    )
    weekly = aggregate_daily_klines_to_weeks(rows)
    assert len(weekly) == 1
    assert weekly[0]["quote_volume"] == 7_000.0
    assert weekly[0]["taker_buy_quote_volume"] == 4_200.0
    assert weekly[0]["source_kind"] == "binance_spot_1d_klines_proxy"
    assert aggregate_daily_klines_to_weeks(rows[:-1]) == []


def test_daily_kline_pagination_is_injected_and_half_open() -> None:
    calls: list[dict] = []

    def fetcher(_url: str, params: dict) -> list:
        calls.append(params)
        return [_kline(day) for day in range(7)]

    rows = fetch_daily_klines(
        symbol="BTCUSDT",
        base_asset="BTC",
        start_ms=MONDAY_MS,
        end_ms=MONDAY_MS + 7 * 86_400_000,
        fetcher=fetcher,
    )
    assert len(rows) == 7
    assert calls[0]["endTime"] == MONDAY_MS + 7 * 86_400_000 - 1


def test_multi_asset_week_uses_causal_dynamic_universe() -> None:
    snapshot = parse_exchange_info(
        _exchange_info(*(f"A{i:02d}" for i in range(30))),
        observed_at=datetime(2023, 12, 31, tzinfo=UTC),
    )
    seen: list[str] = []

    def fetcher(_url: str, params: dict) -> list:
        seen.append(params["symbol"])
        return [_kline(day) for day in range(7)]

    rows, diagnostics = fetch_dynamic_universe_week(
        snapshots=[snapshot],
        week_start=MONDAY_MS // 1_000,
        kraken_base_assets=[f"A{i:02d}" for i in range(30)],
        fetcher=fetcher,
    )
    assert len(rows) == 30
    assert diagnostics["complete_asset_count"] == 30
    assert seen == [f"A{i:02d}USDT" for i in range(30)]


def test_bounded_aggtrades_equivalence_audit_requires_hash() -> None:
    timestamp_ms = MONDAY_MS
    payload = _zip_csv(
        [
            ["1", "100", "2", "1", "1", str(timestamp_ms), "false", "true"],
            ["2", "100", "1", "2", "2", str(timestamp_ms + 1), "true", "true"],
        ]
    )
    digest = hashlib.sha256(payload).hexdigest()
    ticks, manifest = fetch_monthly_aggtrades(
        symbol="BTCUSDT",
        base_asset="BTC",
        month="2024-01",
        expected_sha256=digest,
        fetcher=lambda _url: payload,
    )
    assert manifest.sha256 == digest
    assert ticks[0]["quote_volume"] == 300.0
    assert ticks[0]["taker_buy_quote_volume"] == 200.0
    proxy = [
        {
            "base_asset": "BTC",
            "week_start": ticks[0]["week_start"],
            "quote_volume": 300.0,
            "taker_buy_quote_volume": 200.0,
        }
    ]
    audit = compare_weekly_flow_sources(proxy, ticks)
    assert audit["sign_agreement_rate"] == 1.0
    assert audit["mean_absolute_imbalance_error"] == pytest.approx(0.0)
    with pytest.raises(CollectorError, match="checksum mismatch"):
        fetch_monthly_aggtrades(
            symbol="BTCUSDT",
            base_asset="BTC",
            month="2024-01",
            expected_sha256="0" * 64,
            fetcher=lambda _url: payload,
        )


def test_aggtrades_accepts_microsecond_timestamps() -> None:
    timestamp_us = MONDAY_MS * 1_000
    payload = _zip_csv(
        [["1", "100", "1", "1", "1", str(timestamp_us), "false", "true"]]
    )
    rows = aggregate_aggtrades_zip(payload, symbol="BTCUSDT", base_asset="BTC")
    assert rows[0]["week_start"] == MONDAY_MS // 1_000


def test_daily_archive_supports_bounded_equivalence_sample() -> None:
    payload = _zip_csv(
        [["1", "100", "1", "1", "1", str(MONDAY_MS), "false", "true"]]
    )
    digest = hashlib.sha256(payload).hexdigest()
    rows, manifest = fetch_daily_aggtrades(
        symbol="BTCUSDT",
        base_asset="BTC",
        day="2024-01-01",
        expected_sha256=digest,
        fetcher=lambda _url: payload,
    )
    proxy = [
        {
            "base_asset": "BTC",
            "timestamp": MONDAY_MS // 1_000,
            "quote_volume": 100.0,
            "taker_buy_quote_volume": 100.0,
        }
    ]
    assert manifest.cadence == "daily"
    assert compare_daily_flow_sources(proxy, rows)["sign_agreement_rate"] == 1.0
