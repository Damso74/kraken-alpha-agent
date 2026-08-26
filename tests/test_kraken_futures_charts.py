from __future__ import annotations

import pytest

from src.data.collectors._common import CollectorError
from src.data.collectors.kraken_futures_charts import (
    fetch_analytics,
    fetch_candles,
    parse_analytics_page,
    parse_candles_page,
)


def test_parse_candles_normalises_milliseconds_and_sorts() -> None:
    rows, more = parse_candles_page(
        {
            "candles": [
                {
                    "time": 1_700_003_600_000,
                    "open": "101",
                    "high": "103",
                    "low": "100",
                    "close": "102",
                    "volume": "2.5",
                },
                {
                    "time": 1_700_000_000_000,
                    "open": "100",
                    "high": "102",
                    "low": "99",
                    "close": "101",
                    "volume": "1.5",
                },
            ],
            "more_candles": True,
        }
    )
    assert more is True
    assert [row["timestamp"] for row in rows] == [1_700_000_000, 1_700_003_600]
    assert rows[0]["open"] == 100.0


def test_parse_scalar_and_ohlc_analytics() -> None:
    scalar, more = parse_analytics_page(
        "liquidation-volume",
        {
            "result": {
                "timestamp": [1_700_000_000, 1_700_003_600],
                "data": ["0", "12.5"],
                "more": False,
            }
        },
    )
    assert more is False
    assert scalar[1]["liquidation_volume"] == 12.5

    ohlc, _ = parse_analytics_page(
        "open-interest",
        {
            "result": {
                "timestamp": [1_700_000_000_000],
                "data": [["100", "105", "95", "102"]],
                "more": False,
            }
        },
    )
    assert ohlc == [
        {
            "timestamp": 1_700_000_000,
            "open_interest_open": 100.0,
            "open_interest_high": 105.0,
            "open_interest_low": 95.0,
            "open_interest_close": 102.0,
        }
    ]


def test_fetch_candles_advances_cursor_and_dedupes() -> None:
    calls: list[dict] = []

    def fetcher(_url: str, params: dict | None) -> dict:
        assert params is not None
        calls.append(dict(params))
        if len(calls) == 1:
            return {
                "candles": [
                    {
                        "time": 1_700_000_000_000,
                        "open": "100",
                        "high": "101",
                        "low": "99",
                        "close": "100",
                        "volume": "1",
                    },
                    {
                        "time": 1_700_003_600_000,
                        "open": "100",
                        "high": "102",
                        "low": "100",
                        "close": "101",
                        "volume": "2",
                    },
                ],
                "more_candles": True,
            }
        return {
            "candles": [
                {
                    "time": 1_700_007_200_000,
                    "open": "101",
                    "high": "103",
                    "low": "100",
                    "close": "102",
                    "volume": "3",
                }
            ],
            "more_candles": False,
        }

    rows = fetch_candles(
        "PF_XBTUSD",
        "1h",
        since=1_700_000_000,
        to=1_700_010_800,
        fetcher=fetcher,
        pause_seconds=0,
    )
    assert len(rows) == 3
    assert calls[1]["from"] == 1_700_007_200


def test_fetch_analytics_advances_cursor() -> None:
    calls: list[dict] = []

    def fetcher(_url: str, params: dict | None) -> dict:
        assert params is not None
        calls.append(dict(params))
        if len(calls) == 1:
            return {
                "result": {
                    "timestamp": [1_700_000_000, 1_700_003_600],
                    "data": ["1", "2"],
                    "more": True,
                }
            }
        return {
            "result": {
                "timestamp": [1_700_007_200],
                "data": ["3"],
                "more": False,
            }
        }

    rows = fetch_analytics(
        "PF_XBTUSD",
        "aggressor-differential",
        interval_seconds=3600,
        since=1_700_000_000,
        to=1_700_010_800,
        fetcher=fetcher,
        pause_seconds=0,
    )
    assert [row["aggressor_differential"] for row in rows] == [1.0, 2.0, 3.0]
    assert calls[1]["since"] == 1_700_007_200


def test_fetch_analytics_fails_closed_on_empty_continuation() -> None:
    def fetcher(_url: str, _params: dict | None) -> dict:
        return {"result": {"timestamp": [], "data": [], "more": True}}

    with pytest.raises(CollectorError, match="more=true but no rows"):
        fetch_analytics(
            "PF_XBTUSD",
            "liquidation-volume",
            interval_seconds=3600,
            since=1_700_000_000,
            to=1_700_010_800,
            fetcher=fetcher,
            pause_seconds=0,
        )
