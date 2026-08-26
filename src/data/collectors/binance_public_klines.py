"""Strict no-auth Binance daily kline collector for BTCUSDT research.

The public market-data host mirrors ``GET /api/v3/klines`` without requiring
credentials.  This module deliberately exposes only the frozen research input:
UTC daily BTCUSDT candles over a half-open millisecond window ``[start, end)``.
No missing candle is synthesized or forward-filled.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from typing import Any

from ._common import CollectorError, HttpFetcherFn, default_http_fetcher

BINANCE_PUBLIC_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
BINANCE_SYMBOL = "BTCUSDT"
BINANCE_INTERVAL = "1d"
BINANCE_MAX_LIMIT = 1000
DAY_MILLISECONDS = 86_400_000
DEFAULT_MAX_PAGES = 100
DEFAULT_PAGE_PAUSE_SECONDS = 0.05


def _parse_open_time_ms(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CollectorError(f"invalid Binance kline open time: {value!r}")
    if value < 0 or value % DAY_MILLISECONDS != 0:
        raise CollectorError(
            f"Binance daily kline open time is not a UTC day boundary: {value!r}"
        )
    return value


def _positive_float(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise CollectorError(f"invalid Binance {label}: {value!r}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CollectorError(f"invalid Binance {label}: {value!r}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise CollectorError(f"invalid Binance {label}: {value!r}")
    return parsed


def _non_negative_float(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise CollectorError(f"invalid Binance {label}: {value!r}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CollectorError(f"invalid Binance {label}: {value!r}") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise CollectorError(f"invalid Binance {label}: {value!r}")
    return parsed


def _insert_unique(
    rows_by_timestamp: dict[int, dict[str, Any]],
    row: dict[str, Any],
) -> None:
    timestamp = int(row["timestamp"])
    previous = rows_by_timestamp.get(timestamp)
    if previous is not None and previous != row:
        raise CollectorError(
            f"conflicting Binance daily klines for timestamp={timestamp}"
        )
    rows_by_timestamp[timestamp] = row


def parse_klines_page(payload: Any) -> list[dict[str, Any]]:
    """Parse one Binance kline page into strictly ordered daily rows.

    Identical duplicate candles are collapsed.  Conflicting duplicates and
    out-of-order source rows fail closed instead of silently changing history.
    """

    if not isinstance(payload, list):
        raise CollectorError(
            f"Binance klines payload is not a list: {type(payload).__name__}"
        )

    rows_by_timestamp: dict[int, dict[str, Any]] = {}
    previous_open_ms: int | None = None
    for raw in payload:
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, (str, bytes))
            or len(raw) < 11
        ):
            raise CollectorError("Binance kline row must contain at least 11 fields")

        open_ms = _parse_open_time_ms(raw[0])
        if previous_open_ms is not None and open_ms < previous_open_ms:
            raise CollectorError("Binance klines are not ordered by open time")
        previous_open_ms = open_ms

        quote_volume = _non_negative_float(raw[7], label="quote volume")
        taker_buy_quote_volume = _non_negative_float(
            raw[10], label="taker buy quote volume"
        )
        if taker_buy_quote_volume > quote_volume:
            raise CollectorError(
                "Binance taker buy quote volume exceeds total quote volume"
            )

        row = {
            "timestamp": open_ms // 1000,
            "open": _positive_float(raw[1], label="open"),
            "close": _positive_float(raw[4], label="close"),
            "quote_volume": quote_volume,
            "taker_buy_quote_volume": taker_buy_quote_volume,
        }
        _insert_unique(rows_by_timestamp, row)

    return [rows_by_timestamp[ts] for ts in sorted(rows_by_timestamp)]


def fetch_daily_klines(
    *,
    start_ms: int,
    end_ms: int,
    symbol: str = BINANCE_SYMBOL,
    fetcher: HttpFetcherFn = default_http_fetcher,
    max_pages: int = DEFAULT_MAX_PAGES,
    pause_seconds: float = DEFAULT_PAGE_PAUSE_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch BTCUSDT UTC daily klines over ``[start_ms, end_ms)``.

    Binance's ``endTime`` is inclusive, hence ``end_ms - 1`` on the wire.  A
    full page advances by one daily bucket after its final candle.  Identical
    pagination overlaps are deduplicated; conflicting history fails closed.
    """

    if symbol != BINANCE_SYMBOL:
        raise ValueError(f"unsupported Binance symbol: {symbol}")
    if (
        isinstance(start_ms, bool)
        or isinstance(end_ms, bool)
        or not isinstance(start_ms, int)
        or not isinstance(end_ms, int)
        or start_ms < 0
        or end_ms <= start_ms
    ):
        raise ValueError("invalid Binance kline window")
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    if pause_seconds < 0:
        raise ValueError("pause_seconds must be non-negative")

    cursor_ms = start_ms
    rows_by_timestamp: dict[int, dict[str, Any]] = {}

    for page_index in range(max_pages):
        payload = fetcher(
            BINANCE_PUBLIC_KLINES_URL,
            {
                "symbol": BINANCE_SYMBOL,
                "interval": BINANCE_INTERVAL,
                "startTime": cursor_ms,
                "endTime": end_ms - 1,
                "limit": BINANCE_MAX_LIMIT,
            },
        )
        raw_page_size = len(payload) if isinstance(payload, list) else 0
        page_rows = parse_klines_page(payload)
        if not page_rows:
            return [rows_by_timestamp[ts] for ts in sorted(rows_by_timestamp)]

        page_open_ms: list[int] = []
        for row in page_rows:
            open_ms = int(row["timestamp"]) * 1000
            if open_ms < start_ms or open_ms >= end_ms:
                raise CollectorError(
                    f"Binance returned a candle outside the requested window: {open_ms}"
                )
            _insert_unique(rows_by_timestamp, row)
            page_open_ms.append(open_ms)

        next_cursor_ms = max(page_open_ms) + DAY_MILLISECONDS
        if next_cursor_ms <= cursor_ms:
            raise CollectorError("Binance kline pagination cursor did not advance")
        cursor_ms = next_cursor_ms

        if raw_page_size < BINANCE_MAX_LIMIT or cursor_ms >= end_ms:
            return [rows_by_timestamp[ts] for ts in sorted(rows_by_timestamp)]
        if page_index + 1 < max_pages and pause_seconds > 0:
            time.sleep(pause_seconds)

    raise CollectorError(f"Binance klines exceeded max_pages={max_pages}")
