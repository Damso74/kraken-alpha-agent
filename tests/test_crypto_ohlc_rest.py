"""Regression tests for :mod:`src.crypto_ohlc_rest`.

The tests inject a fake fetcher so the suite never touches the network
or shells out to Kraken. They cover:

- ``parse_rest_ohlc_payload`` accepts the canonical REST shape, walks
  ``result`` keys to find the OHLC array, and rejects non-empty error
  arrays.
- ``normalize_crypto_pair`` translates bare tickers to Kraken REST
  pair names (``BTC`` → ``XBTUSD``) and accepts slash forms.
- ``fetch_crypto_ohlc_paginated`` stops cleanly on no-progress, on
  cursor stalls, on ``max_pages``, and on reaching ``target_candles``.
"""

from __future__ import annotations

import pytest

from src.crypto_ohlc_rest import (
    CryptoOHLCFetchError,
    fetch_crypto_ohlc_paginated,
    normalize_crypto_pair,
    parse_rest_ohlc_payload,
)


def _ohlc_row(ts: int, base_price: float = 100.0) -> list:
    return [
        ts,
        f"{base_price:.4f}",
        f"{base_price + 0.5:.4f}",
        f"{base_price - 0.5:.4f}",
        f"{base_price + 0.1:.4f}",
        f"{base_price:.4f}",
        "10.5",
        25,
    ]


def test_normalize_crypto_pair_translates_btc_to_xbtusd() -> None:
    assert normalize_crypto_pair("BTC") == "XBTUSD"
    assert normalize_crypto_pair("BTC/USD") == "XBTUSD"
    assert normalize_crypto_pair("ETH") == "ETHUSD"
    assert normalize_crypto_pair("xbt") == "XBTUSD"


def test_normalize_crypto_pair_passes_through_unknown_uppercased() -> None:
    # Unknown bare ticker is uppercased so the caller can experiment.
    assert normalize_crypto_pair("foo") == "FOO"


def test_parse_payload_accepts_canonical_rest_shape() -> None:
    payload = {
        "error": [],
        "result": {
            "XXBTZUSD": [
                _ohlc_row(1_700_000_000),
                _ohlc_row(1_700_003_600, 101.0),
            ],
            "last": 1_700_003_600,
        },
    }
    rows, cursor = parse_rest_ohlc_payload(payload, pair_hint="XBTUSD")
    assert len(rows) == 2
    assert rows[0].timestamp == 1_700_000_000
    assert rows[1].open == pytest.approx(101.0)
    assert cursor == 1_700_003_600


def test_parse_payload_raises_on_non_empty_error_array() -> None:
    payload = {"error": ["EGeneral:Invalid arguments"], "result": {}}
    with pytest.raises(CryptoOHLCFetchError):
        parse_rest_ohlc_payload(payload)


def test_parse_payload_tolerates_empty_result() -> None:
    rows, cursor = parse_rest_ohlc_payload({"error": [], "result": {"last": 0}})
    assert rows == []
    assert cursor == 0


def test_fetch_paginated_stops_when_target_reached() -> None:
    pages = [
        {
            "error": [],
            "result": {
                "XXBTZUSD": [_ohlc_row(1_700_000_000 + i * 3600) for i in range(5)],
                "last": 1_700_000_000 + 4 * 3600,
            },
        },
    ]
    call_count = {"n": 0}

    def fetcher(pair: str, interval_min: int, since):
        call_count["n"] += 1
        return pages[call_count["n"] - 1]

    rows = fetch_crypto_ohlc_paginated(
        "XBTUSD",
        interval_min=60,
        target_candles=3,
        fetcher=fetcher,
        sleep_between_pages=0,
    )
    assert len(rows) == 3
    assert call_count["n"] == 1


def test_fetch_paginated_stops_on_no_progress() -> None:
    # Same payload returned twice → second call has zero new rows → loop exits.
    payload = {
        "error": [],
        "result": {
            "XXBTZUSD": [_ohlc_row(1_700_000_000 + i * 3600) for i in range(3)],
            "last": 1_700_000_000 + 2 * 3600,
        },
    }
    call_count = {"n": 0}

    def fetcher(pair: str, interval_min: int, since):
        call_count["n"] += 1
        return payload

    rows = fetch_crypto_ohlc_paginated(
        "XBTUSD",
        interval_min=60,
        target_candles=100,
        fetcher=fetcher,
        sleep_between_pages=0,
    )
    assert len(rows) == 3
    assert call_count["n"] == 2  # one to fetch, one to detect no progress


def test_fetch_paginated_respects_max_pages_ceiling() -> None:
    """Hand the fetcher unique pages forever — verify ``max_pages`` clamps."""
    counter = {"n": 0}

    def fetcher(pair: str, interval_min: int, since):
        counter["n"] += 1
        base = 1_700_000_000 + counter["n"] * 3600 * 10
        return {
            "error": [],
            "result": {
                "XXBTZUSD": [_ohlc_row(base + i * 3600) for i in range(5)],
                "last": base + 4 * 3600,
            },
        }

    rows = fetch_crypto_ohlc_paginated(
        "XBTUSD",
        interval_min=60,
        target_candles=10_000,
        fetcher=fetcher,
        max_pages=3,
        sleep_between_pages=0,
    )
    assert counter["n"] == 3
    assert len(rows) == 15
