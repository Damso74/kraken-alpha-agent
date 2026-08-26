from __future__ import annotations

from collections.abc import Mapping
from itertools import pairwise
from typing import Any

import pytest

from src.data.collectors._common import CollectorError
from src.data.collectors.binance_public_klines import (
    BINANCE_MAX_LIMIT,
    BINANCE_PUBLIC_KLINES_URL,
    DAY_MILLISECONDS,
    fetch_daily_klines,
    parse_klines_page,
)

DAY_1 = 1_699_920_000_000
DAY_2 = DAY_1 + DAY_MILLISECONDS


def _kline(
    open_ms: int,
    *,
    open_price: str = "100",
    close_price: str = "101",
    quote_volume: str = "1000",
    taker_buy_quote_volume: str = "600",
) -> list[Any]:
    return [
        open_ms,
        open_price,
        "102",
        "99",
        close_price,
        "10",
        open_ms + DAY_MILLISECONDS - 1,
        quote_volume,
        123,
        "6",
        taker_buy_quote_volume,
        "0",
    ]


def test_parse_page_normalises_schema_and_deduplicates_identical_rows() -> None:
    rows = parse_klines_page([_kline(DAY_1), _kline(DAY_1), _kline(DAY_2)])

    assert rows == [
        {
            "timestamp": DAY_1 // 1000,
            "open": 100.0,
            "close": 101.0,
            "quote_volume": 1000.0,
            "taker_buy_quote_volume": 600.0,
        },
        {
            "timestamp": DAY_2 // 1000,
            "open": 100.0,
            "close": 101.0,
            "quote_volume": 1000.0,
            "taker_buy_quote_volume": 600.0,
        },
    ]


def test_parse_page_fails_closed_on_conflicting_duplicate() -> None:
    with pytest.raises(CollectorError, match="conflicting"):
        parse_klines_page([_kline(DAY_1), _kline(DAY_1, close_price="102")])


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"rows": []}, "not a list"),
        ([[DAY_1, "100"]], "at least 11"),
        ([_kline(DAY_2), _kline(DAY_1)], "not ordered"),
        ([_kline(DAY_1 + 1)], "UTC day boundary"),
        ([_kline(DAY_1, quote_volume="nan")], "quote volume"),
        (
            [_kline(DAY_1, quote_volume="100", taker_buy_quote_volume="101")],
            "exceeds",
        ),
    ],
)
def test_parse_page_rejects_malformed_or_inconsistent_data(
    payload: Any, message: str
) -> None:
    with pytest.raises(CollectorError, match=message):
        parse_klines_page(payload)


def test_fetch_uses_half_open_window_and_strict_wire_contract() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fetcher(url: str, params: Mapping[str, Any] | None) -> list[list[Any]]:
        assert params is not None
        calls.append((url, dict(params)))
        return [_kline(DAY_1), _kline(DAY_2)]

    rows = fetch_daily_klines(
        start_ms=DAY_1,
        end_ms=DAY_2 + DAY_MILLISECONDS,
        fetcher=fetcher,
        pause_seconds=0,
    )

    assert [row["timestamp"] for row in rows] == [DAY_1 // 1000, DAY_2 // 1000]
    assert calls == [
        (
            BINANCE_PUBLIC_KLINES_URL,
            {
                "symbol": "BTCUSDT",
                "interval": "1d",
                "startTime": DAY_1,
                "endTime": DAY_2 + DAY_MILLISECONDS - 1,
                "limit": BINANCE_MAX_LIMIT,
            },
        )
    ]


def test_fetch_preserves_missing_days_without_imputation() -> None:
    day_3 = DAY_2 + DAY_MILLISECONDS

    def fetcher(
        _url: str, _params: Mapping[str, Any] | None
    ) -> list[list[Any]]:
        return [_kline(DAY_1), _kline(day_3)]

    rows = fetch_daily_klines(
        start_ms=DAY_1,
        end_ms=day_3 + DAY_MILLISECONDS,
        fetcher=fetcher,
        pause_seconds=0,
    )

    assert [row["timestamp"] for row in rows] == [DAY_1 // 1000, day_3 // 1000]


def test_fetch_paginates_full_page_and_keeps_order() -> None:
    calls: list[dict[str, Any]] = []
    first_page = [_kline(DAY_1 + index * DAY_MILLISECONDS) for index in range(1000)]
    final_day = DAY_1 + 1000 * DAY_MILLISECONDS

    def fetcher(
        _url: str, params: Mapping[str, Any] | None
    ) -> list[list[Any]]:
        assert params is not None
        calls.append(dict(params))
        if len(calls) == 1:
            return first_page
        return [_kline(final_day)]

    rows = fetch_daily_klines(
        start_ms=DAY_1,
        end_ms=final_day + DAY_MILLISECONDS,
        fetcher=fetcher,
        pause_seconds=0,
    )

    assert len(rows) == 1001
    assert calls[1]["startTime"] == final_day
    assert rows[-1]["timestamp"] == final_day // 1000
    assert all(
        int(left["timestamp"]) < int(right["timestamp"])
        for left, right in pairwise(rows)
    )


def test_fetch_fails_closed_on_out_of_window_data_and_page_cap() -> None:
    def out_of_window(
        _url: str, _params: Mapping[str, Any] | None
    ) -> list[list[Any]]:
        return [_kline(DAY_2)]

    with pytest.raises(CollectorError, match="outside"):
        fetch_daily_klines(
            start_ms=DAY_1,
            end_ms=DAY_2,
            fetcher=out_of_window,
            pause_seconds=0,
        )

    full_page = [_kline(DAY_1 + index * DAY_MILLISECONDS) for index in range(1000)]

    def never_finishes(
        _url: str, _params: Mapping[str, Any] | None
    ) -> list[list[Any]]:
        return full_page

    with pytest.raises(CollectorError, match="exceeded max_pages=1"):
        fetch_daily_klines(
            start_ms=DAY_1,
            end_ms=DAY_1 + 2000 * DAY_MILLISECONDS,
            fetcher=never_finishes,
            max_pages=1,
            pause_seconds=0,
        )


def test_fetch_validates_frozen_symbol_and_window() -> None:
    with pytest.raises(ValueError, match="unsupported Binance symbol"):
        fetch_daily_klines(start_ms=DAY_1, end_ms=DAY_2, symbol="ETHUSDT")
    with pytest.raises(ValueError, match="invalid Binance kline window"):
        fetch_daily_klines(start_ms=DAY_1, end_ms=DAY_1)
