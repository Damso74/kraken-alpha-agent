"""Tests for src.kraken_ohlc_paginated.

Cover the four spec'd cases:
1. Forward pagination over 2 batches of 720 → 1440 candles, sorted ascending.
2. Stop condition: identical ``last`` cursor between two calls (no progress).
3. Error handling: ``{"error": [...]}`` payloads raise OHLCFetchError.
4. Limit handling: ``target_candles`` is honoured (we never return more rows
   than asked, and we stop as soon as we have enough).

Plus a few defensive cases:
- Validates ``parse_ohlc_payload`` accepts the REST-shaped envelope.
- Empty pages cause an early stop.
- Invalid arguments are rejected up front.
"""

from __future__ import annotations

import pytest

from src.kraken_ohlc_paginated import (
    KRAKEN_OHLC_CAP_PER_CALL,
    OHLCFetchError,
    OHLCRow,
    fetch_ohlc_paginated,
    parse_ohlc_payload,
)


PAIR = "AAPLx/USD"


def _build_page(start_ts: int, count: int, *, interval_seconds: int = 60) -> dict:
    """Build a Kraken-shaped OHLC JSON payload with `count` candles starting at start_ts."""
    rows: list[list] = []
    for i in range(count):
        ts = start_ts + i * interval_seconds
        rows.append([ts, "100.0", "101.0", "99.0", "100.5", "100.4", "12.34", 5])
    last = rows[-1][0] if rows else start_ts
    return {PAIR: rows, "last": last}


def _make_fetcher(pages: list[dict]):
    """Build a stateful fetcher that pops one page per call."""
    state = {"calls": 0, "since_log": []}

    def _fetch(pair: str, interval_min: int, since):
        state["calls"] += 1
        state["since_log"].append(since)
        if state["calls"] > len(pages):
            # No more pages; emulate "no new rows".
            return {pair: [], "last": pages[-1].get("last") if pages else None}
        return pages[state["calls"] - 1]

    _fetch.state = state
    return _fetch


# --- parse_ohlc_payload --------------------------------------------------


def test_parse_canonical_shape():
    payload = _build_page(start_ts=1_700_000_000, count=3)
    rows, cursor = parse_ohlc_payload(payload, pair_hint=PAIR)
    assert len(rows) == 3
    assert all(isinstance(r, OHLCRow) for r in rows)
    assert [r.timestamp for r in rows] == [1_700_000_000, 1_700_000_060, 1_700_000_120]
    assert cursor == 1_700_000_120


def test_parse_rest_shape():
    payload = {"error": [], "result": _build_page(start_ts=1_700_000_000, count=2)}
    rows, cursor = parse_ohlc_payload(payload, pair_hint=PAIR)
    assert len(rows) == 2
    assert cursor == 1_700_000_060


def test_parse_error_array_raises():
    with pytest.raises(OHLCFetchError, match="Kraken OHLC error"):
        parse_ohlc_payload({"error": ["EGeneral:Invalid arguments"]})


def test_parse_non_dict_raises():
    with pytest.raises(OHLCFetchError, match="not a dict"):
        parse_ohlc_payload([1, 2, 3])  # type: ignore[arg-type]


# --- fetch_ohlc_paginated ------------------------------------------------


def test_pagination_two_full_pages_concatenates_in_order():
    """1440 candles arrive across two 720-row batches; result must be sorted ascending."""
    page1 = _build_page(start_ts=1_700_000_000, count=KRAKEN_OHLC_CAP_PER_CALL)
    page2_start = page1["last"] + 60  # contiguous, no overlap
    page2 = _build_page(start_ts=page2_start, count=KRAKEN_OHLC_CAP_PER_CALL)

    fetcher = _make_fetcher([page1, page2])
    rows = fetch_ohlc_paginated(
        PAIR,
        interval_min=1,
        target_candles=2 * KRAKEN_OHLC_CAP_PER_CALL,
        fetcher=fetcher,
        max_pages=5,
    )

    assert len(rows) == 1440
    timestamps = [r.timestamp for r in rows]
    assert timestamps == sorted(timestamps)
    assert timestamps[0] == 1_700_000_000
    # First call uses no `since`; second call should pass page1's `last`.
    assert fetcher.state["since_log"][0] is None
    assert fetcher.state["since_log"][1] == page1["last"]
    assert fetcher.state["calls"] == 2


def test_stop_condition_identical_last_cursor():
    """If the second page returns the same `last` as page 1 (no progression), we stop."""
    page1 = _build_page(start_ts=1_700_000_000, count=KRAKEN_OHLC_CAP_PER_CALL)
    # page2 has no rows but reuses the same `last` cursor → stop without infinite loop.
    page2 = {PAIR: [], "last": page1["last"]}
    page3_should_never_be_called = _build_page(start_ts=1_700_500_000, count=10)

    fetcher = _make_fetcher([page1, page2, page3_should_never_be_called])
    rows = fetch_ohlc_paginated(
        PAIR,
        interval_min=1,
        target_candles=10_000,
        fetcher=fetcher,
        max_pages=10,
    )
    assert len(rows) == KRAKEN_OHLC_CAP_PER_CALL
    # No-progress stop: we stop after the second call returns 0 new rows.
    assert fetcher.state["calls"] == 2


def test_kraken_error_propagates_as_exception():
    """A Kraken `{"error": [...]}` payload mid-pagination must raise a clear exception."""
    page1 = _build_page(start_ts=1_700_000_000, count=KRAKEN_OHLC_CAP_PER_CALL)
    err_payload = {"error": ["EGeneral:Internal error"]}
    fetcher = _make_fetcher([page1, err_payload])

    with pytest.raises(OHLCFetchError, match="Internal error"):
        fetch_ohlc_paginated(
            PAIR,
            interval_min=1,
            target_candles=2 * KRAKEN_OHLC_CAP_PER_CALL,
            fetcher=fetcher,
            max_pages=5,
        )


def test_target_candles_is_respected():
    """Even when many pages are available, output is capped at target_candles."""
    page1 = _build_page(start_ts=1_700_000_000, count=KRAKEN_OHLC_CAP_PER_CALL)
    page2 = _build_page(
        start_ts=page1["last"] + 60, count=KRAKEN_OHLC_CAP_PER_CALL
    )
    page3 = _build_page(
        start_ts=page2["last"] + 60, count=KRAKEN_OHLC_CAP_PER_CALL
    )

    fetcher = _make_fetcher([page1, page2, page3])
    target = 1_000  # less than 720 * 3
    rows = fetch_ohlc_paginated(
        PAIR,
        interval_min=1,
        target_candles=target,
        fetcher=fetcher,
        max_pages=10,
    )
    assert len(rows) == target
    # When target is reached after page 2 (1440 rows accumulated > 1000),
    # we should not call page 3.
    assert fetcher.state["calls"] == 2


def test_invalid_arguments_rejected_upfront():
    with pytest.raises(ValueError):
        fetch_ohlc_paginated(PAIR, interval_min=0, target_candles=10, fetcher=lambda *a, **k: {})
    with pytest.raises(ValueError):
        fetch_ohlc_paginated(PAIR, interval_min=15, target_candles=0, fetcher=lambda *a, **k: {})


def test_empty_first_page_returns_empty():
    fetcher = _make_fetcher([{PAIR: [], "last": None}])
    rows = fetch_ohlc_paginated(
        PAIR,
        interval_min=15,
        target_candles=720,
        fetcher=fetcher,
        max_pages=5,
    )
    assert rows == []
    assert fetcher.state["calls"] == 1


def test_overlapping_pages_dedupe_by_timestamp():
    """If page 2 overlaps page 1 by a few rows, the merged output has unique timestamps."""
    page1 = _build_page(start_ts=1_700_000_000, count=10)
    # page2 overlaps last 3 candles of page1.
    page2 = _build_page(start_ts=page1[PAIR][-3][0], count=10)
    fetcher = _make_fetcher([page1, page2, {PAIR: [], "last": page2["last"]}])
    rows = fetch_ohlc_paginated(
        PAIR,
        interval_min=1,
        target_candles=100,
        fetcher=fetcher,
        max_pages=5,
    )
    timestamps = [r.timestamp for r in rows]
    assert timestamps == sorted(set(timestamps))
    # 10 + (10 - 3) overlapping = 17 unique
    assert len(rows) == 17
