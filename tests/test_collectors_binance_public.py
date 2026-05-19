"""Hermetic tests for :mod:`src.data.collectors.binance_public`."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.data.collectors.binance_public import (
    CollectorError,
    default_ohlc_daily_cache_path,
    fetch_binance_daily_klines,
    fetch_ohlc_daily_cache_only,
    fetch_ohlc_daily_with_cache,
    load_ohlc_daily_cache,
    normalize_binance_symbol,
    parse_binance_klines,
    parse_ohlc_candle_rows,
    save_ohlc_daily_cache,
)


def _ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _candle(d: date, close: float) -> dict:
    return {
        "timestamp": _ts(d),
        "open": close - 10,
        "high": close + 20,
        "low": close - 20,
        "close": close,
        "vwap": close,
        "volume": 100.0,
    }


BINANCE_KLINE_FIXTURE = [
    [
        _ts(date(2026, 5, 17)) * 1000,
        "65000.0",
        "66000.0",
        "64000.0",
        "65500.0",
        "123.45",
        0,
        "8000000.0",
    ],
    [
        _ts(date(2026, 5, 18)) * 1000,
        "65500.0",
        "67000.0",
        "65000.0",
        "66500.0",
        "150.0",
        0,
        "9900000.0",
    ],
]


def test_normalize_binance_symbol_maps_btc() -> None:
    assert normalize_binance_symbol("BTC") == "BTCUSDT"
    assert normalize_binance_symbol("btc/usd") == "BTCUSDT"
    assert normalize_binance_symbol("ETH") == "ETHUSDT"


def test_parse_binance_klines_normalizes_rows() -> None:
    rows = parse_binance_klines(BINANCE_KLINE_FIXTURE)
    assert len(rows) == 2
    assert rows[0]["close"] == 65500.0
    assert rows[0]["volume"] == 123.45
    assert rows[1]["timestamp"] - rows[0]["timestamp"] == 86400


def test_parse_binance_klines_rejects_non_list() -> None:
    with pytest.raises(CollectorError):
        parse_binance_klines({})


def test_parse_ohlc_candle_rows_drops_invalid() -> None:
    rows = parse_ohlc_candle_rows(
        [
            _candle(date(2026, 5, 17), 100.0),
            {"timestamp": "bad", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ]
    )
    assert len(rows) == 1
    assert rows[0]["close"] == 100.0


def test_default_ohlc_daily_cache_path() -> None:
    path = default_ohlc_daily_cache_path("btc")
    assert path.name == "ohlc_daily_BTC.json"
    assert path.parent.name == "collector_cache"


def test_save_and_load_ohlc_daily_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "ohlc_daily_BTC.json"
    today = datetime.now(timezone.utc).date()
    candles = [_candle(today - timedelta(days=i), 50_000 + i) for i in range(200, 0, -1)]
    save_ohlc_daily_cache(cache_path, ticker="BTC", rows=candles)

    start = today - timedelta(days=180)
    rows = load_ohlc_daily_cache(
        cache_path,
        ticker="BTC",
        start=start,
        end=today,
        min_rows=30,
    )
    assert len(rows) >= 30
    assert rows[0]["timestamp"] <= rows[-1]["timestamp"]


def test_fetch_ohlc_daily_cache_only_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(CollectorError, match="missing entries"):
        fetch_ohlc_daily_cache_only(
            "BTC",
            30,
            cache_path=tmp_path / "missing.json",
        )


def test_fetch_binance_daily_klines_uses_injected_fetcher() -> None:
    calls: list[dict] = []

    def fake_fetcher(url: str, params: dict) -> list:
        calls.append(params)
        today = datetime.now(timezone.utc).date()
        out = []
        for i in range(35):
            d = today - timedelta(days=i)
            close = 65000.0 + i
            out.append(
                [
                    _ts(d) * 1000,
                    str(close - 10),
                    str(close + 20),
                    str(close - 20),
                    str(close),
                    "100.0",
                    0,
                    "6500000.0",
                ]
            )
        return out

    rows = fetch_binance_daily_klines("BTC", days=30, fetcher=fake_fetcher)
    assert len(rows) >= 30
    assert calls[0]["symbol"] == "BTCUSDT"
    assert calls[0]["interval"] == "1d"


def test_fetch_ohlc_daily_with_cache_hit_skips_network(tmp_path: Path) -> None:
    cache_path = tmp_path / "ohlc_daily_BTC.json"
    today = datetime.now(timezone.utc).date()
    candles = [_candle(today - timedelta(days=i), 50_000 + i) for i in range(200, 0, -1)]
    save_ohlc_daily_cache(cache_path, ticker="BTC", rows=candles)

    def explode(_url: str, _params: dict) -> list:
        raise AssertionError("fetcher must not run on cache hit")

    rows = fetch_ohlc_daily_with_cache(
        "BTC",
        30,
        cache_path=cache_path,
        fetcher=explode,
    )
    assert len(rows) >= 30


def test_fetch_ohlc_daily_with_cache_only_blocks_network(tmp_path: Path) -> None:
    with pytest.raises(CollectorError, match="use_cache_only"):
        fetch_ohlc_daily_with_cache(
            "BTC",
            30,
            cache_path=tmp_path / "empty.json",
            use_cache_only=True,
            fetcher=lambda *_: BINANCE_KLINE_FIXTURE,
        )


def test_fetch_daily_ohlc_dispatch_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import _event_study_common as esc

    sentinel = [{"timestamp": 1, "open": 1, "high": 1, "low": 1, "close": 1, "vwap": 1, "volume": 1}]

    def fake_cache_only(*_a, **_k):
        return sentinel

    monkeypatch.setattr(esc, "fetch_ohlc_daily_cache_only", fake_cache_only)
    out = esc.fetch_daily_ohlc("BTC", 30, ohlc_source=esc.OHLC_SOURCE_CACHE)
    assert out is sentinel


def test_fetch_daily_ohlc_dispatch_kraken_use_cache_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import _event_study_common as esc

    called = {"cache": False}

    def fake_cache_only(*_a, **_k):
        called["cache"] = True
        return []

    monkeypatch.setattr(esc, "fetch_ohlc_daily_cache_only", fake_cache_only)
    esc.fetch_daily_ohlc(
        "BTC",
        30,
        ohlc_source=esc.OHLC_SOURCE_KRAKEN,
        use_cache_only=True,
    )
    assert called["cache"] is True
