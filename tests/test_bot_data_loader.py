"""Tests for src.bot.data_loader — fixtures only, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.bot.data_loader import (
    DataLoaderError,
    load_ohlcv_candles,
    normalize_candle,
    resolve_ohlcv_cache,
    summarize_candles,
    validate_candles,
)


def _write_cache(path: Path, candles: list[dict], interval_minutes: int = 1440) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "test",
        "interval_minutes": interval_minutes,
        "entries": {"candles": candles},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_resolve_daily_cache_path(tmp_path: Path) -> None:
    r = resolve_ohlcv_cache("btc", "1d", tmp_path)
    assert r.path.name == "ohlc_daily_BTC.json"
    assert r.interval_minutes == 1440


def test_missing_cache_blocked(tmp_path: Path) -> None:
    candles, summary = load_ohlcv_candles("BTC", "1h", tmp_path, cache_only=True)
    assert candles == []
    assert summary.status == "blocked_data"


def test_load_and_validate_candles(tmp_path: Path) -> None:
    rows = [
        {
            "timestamp": 1_700_000_000 + i * 3600,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "volume": 10.0,
        }
        for i in range(50)
    ]
    path = tmp_path / "ohlc_1h_BTC.json"
    _write_cache(path, rows, interval_minutes=60)
    candles, summary = load_ohlcv_candles("BTC", "1h", tmp_path, cache_only=True)
    assert summary.status == "available"
    assert len(candles) == 50


def test_reject_duplicate_timestamp() -> None:
    rows = [
        {"timestamp": 100, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1},
        {"timestamp": 100, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1},
    ]
    with pytest.raises(DataLoaderError, match="duplicate"):
        validate_candles(rows)


def test_reject_invalid_ohlc() -> None:
    bad = normalize_candle(
        {"timestamp": 1, "open": 1, "high": 0.5, "low": 2, "close": 1, "volume": 1}
    )
    assert bad is None


def test_summarize_without_full_validation(tmp_path: Path) -> None:
    rows = [
        {
            "timestamp": 1_700_000_000,
            "open": 1,
            "high": 2,
            "low": 0.5,
            "close": 1.5,
            "volume": 1,
        }
    ]
    _write_cache(tmp_path / "ohlc_daily_ETH.json", rows, interval_minutes=1440)
    s = summarize_candles("ETH", "1d", tmp_path)
    assert s.candle_count == 1
    assert s.sha256
