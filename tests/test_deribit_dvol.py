from __future__ import annotations

import pytest

from src.data.collectors._common import CollectorError
from src.data.collectors.deribit_dvol import (
    DERIBIT_DVOL_URL,
    fetch_dvol_candles,
    parse_dvol_page,
)


def test_parse_dvol_page_normalises_sorts_and_deduplicates() -> None:
    rows, continuation = parse_dvol_page(
        {
            "jsonrpc": "2.0",
            "result": {
                "data": [
                    [1_700_086_400_000, "51", "55", "49", "53"],
                    [1_700_000_000_000, 50, 52, 48, 51],
                    [1_700_086_400_000, "51", "55", "49", "53"],
                ],
                "continuation": 1_699_999_999_000,
            },
        }
    )

    assert continuation == 1_699_999_999_000
    assert rows == [
        {
            "timestamp": 1_700_000_000,
            "open": 50.0,
            "high": 52.0,
            "low": 48.0,
            "close": 51.0,
        },
        {
            "timestamp": 1_700_086_400,
            "open": 51.0,
            "high": 55.0,
            "low": 49.0,
            "close": 53.0,
        },
    ]


def test_fetch_dvol_candles_paginates_backwards_and_returns_strict_order() -> None:
    calls: list[tuple[str, dict]] = []

    def fetcher(url: str, params: dict | None) -> dict:
        assert params is not None
        calls.append((url, dict(params)))
        if len(calls) == 1:
            return {
                "result": {
                    "data": [
                        [1_700_172_800_000, 53, 56, 52, 54],
                        [1_700_086_400_000, 51, 55, 49, 53],
                    ],
                    "continuation": 1_700_086_400_000,
                }
            }
        return {
            "result": {
                "data": [
                    [1_700_086_400_000, 51, 55, 49, 53],
                    [1_700_000_000_000, 50, 52, 48, 51],
                ],
                "continuation": None,
            }
        }

    rows = fetch_dvol_candles(
        "BTC",
        start_timestamp_ms=1_700_000_000_000,
        end_timestamp_ms=1_700_259_200_000,
        fetcher=fetcher,
        pause_seconds=0,
    )

    assert calls[0] == (
        DERIBIT_DVOL_URL,
        {
            "currency": "BTC",
            "start_timestamp": 1_700_000_000_000,
            "end_timestamp": 1_700_259_200_000,
            "resolution": "1D",
        },
    )
    assert calls[1][1]["end_timestamp"] == 1_700_086_400_000
    assert [row["timestamp"] for row in rows] == [
        1_700_000_000,
        1_700_086_400,
        1_700_172_800,
    ]


def test_fetch_dvol_candles_keeps_end_exclusive_without_imputation() -> None:
    def fetcher(_url: str, _params: dict | None) -> dict:
        return {
            "result": {
                "data": [
                    [1_700_000_000_000, 50, 52, 48, 51],
                    [1_700_172_800_000, 53, 56, 52, 54],
                    [1_700_259_200_000, 54, 57, 53, 55],
                ],
                "continuation": None,
            }
        }

    rows = fetch_dvol_candles(
        "BTC",
        start_timestamp_ms=1_700_000_000_000,
        end_timestamp_ms=1_700_259_200_000,
        fetcher=fetcher,
    )

    assert [row["timestamp"] for row in rows] == [
        1_700_000_000,
        1_700_172_800,
    ]


def test_fetch_dvol_candles_rejects_api_error() -> None:
    def fetcher(_url: str, _params: dict | None) -> dict:
        return {"error": {"code": 10028, "message": "too_many_requests"}}

    with pytest.raises(CollectorError, match="10028: too_many_requests"):
        fetch_dvol_candles(
            "BTC",
            start_timestamp_ms=1_700_000_000_000,
            end_timestamp_ms=1_700_086_400_000,
            fetcher=fetcher,
        )


def test_fetch_dvol_candles_rejects_non_advancing_continuation() -> None:
    end = 1_700_086_400_000

    def fetcher(_url: str, _params: dict | None) -> dict:
        return {
            "result": {
                "data": [[1_700_000_000_000, 50, 52, 48, 51]],
                "continuation": end,
            }
        }

    with pytest.raises(CollectorError, match="strictly backwards"):
        fetch_dvol_candles(
            "BTC",
            start_timestamp_ms=1_700_000_000_000,
            end_timestamp_ms=end,
            fetcher=fetcher,
        )


def test_fetch_dvol_candles_rejects_empty_continuation_page() -> None:
    def fetcher(_url: str, _params: dict | None) -> dict:
        return {
            "result": {"data": [], "continuation": 1_700_000_000_000}
        }

    with pytest.raises(CollectorError, match="continuation but no rows"):
        fetch_dvol_candles(
            "BTC",
            start_timestamp_ms=1_699_900_000_000,
            end_timestamp_ms=1_700_086_400_000,
            fetcher=fetcher,
        )


def test_parse_dvol_page_rejects_conflicting_duplicate() -> None:
    with pytest.raises(CollectorError, match="conflicting"):
        parse_dvol_page(
            {
                "result": {
                    "data": [
                        [1_700_000_000_000, 50, 52, 48, 51],
                        [1_700_000_000_000, 50, 52, 48, 52],
                    ],
                    "continuation": None,
                }
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"result": {"data": [[1_700_000_000_000, 50, 52, 48]]}},
        {"result": {"data": [[1_700_000_000, 50, 52, 48, 51]]}},
        {"result": {"data": [[1_700_000_000_000, 50, "nan", 48, 51]]}},
        {"result": {"data": [], "continuation": "bad"}},
    ],
)
def test_parse_dvol_page_rejects_malformed_payload(payload: dict) -> None:
    with pytest.raises(CollectorError):
        parse_dvol_page(payload)
