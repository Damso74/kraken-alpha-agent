"""Public Deribit volatility-index (DVOL) candle collector.

The endpoint is read-only and does not require authentication.  Deribit pages
backwards: a non-null ``continuation`` value must be sent as the next
``end_timestamp``.  Rows are returned as UTC Unix seconds and missing candles
are left missing (there is deliberately no forward-fill or interpolation).
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from ._common import CollectorError, HttpFetcherFn, default_http_fetcher

DERIBIT_DVOL_URL = (
    "https://www.deribit.com/api/v2/public/get_volatility_index_data"
)

SUPPORTED_CURRENCIES = frozenset({"BTC", "ETH", "USDC", "USDT", "EURR"})
SUPPORTED_RESOLUTIONS = frozenset({"1", "60", "3600", "43200", "1D"})
DEFAULT_MAX_PAGES = 100
DEFAULT_PAGE_PAUSE_SECONDS = 0.05


def _integer(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CollectorError(f"invalid Deribit {label}: {value!r}")
    return value


def _unix_seconds_from_milliseconds(value: Any) -> int:
    timestamp_ms = _integer(value, label="timestamp")
    if timestamp_ms < 1_000_000_000_000:
        raise CollectorError(
            f"invalid Deribit millisecond timestamp: {timestamp_ms!r}"
        )
    return timestamp_ms // 1000


def _float(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise CollectorError(f"invalid Deribit {label}: {value!r}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CollectorError(f"invalid Deribit {label}: {value!r}") from exc
    if not (-float("inf") < parsed < float("inf")):
        raise CollectorError(f"invalid Deribit {label}: {value!r}")
    return parsed


def _raise_api_error(payload: Mapping[str, Any]) -> None:
    error = payload.get("error")
    if error is None:
        return
    if isinstance(error, Mapping):
        code = error.get("code", "unknown")
        message = error.get("message", "unknown error")
        raise CollectorError(f"Deribit API error {code}: {message}")
    raise CollectorError("Deribit API returned a malformed error object")


def _merge_row(
    rows_by_timestamp: dict[int, dict[str, Any]], row: dict[str, Any]
) -> None:
    timestamp = int(row["timestamp"])
    previous = rows_by_timestamp.get(timestamp)
    if previous is not None and previous != row:
        raise CollectorError(
            f"conflicting Deribit DVOL candles at timestamp {timestamp}"
        )
    rows_by_timestamp[timestamp] = row


def parse_dvol_page(
    payload: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int | None]:
    """Parse one JSON-RPC page into sorted, deduplicated OHLC rows."""

    _raise_api_error(payload)
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise CollectorError("Deribit DVOL payload is missing result")
    raw_data = result.get("data")
    if not isinstance(raw_data, list):
        raise CollectorError("Deribit DVOL result is missing data[]")

    by_timestamp: dict[int, dict[str, Any]] = {}
    for raw_row in raw_data:
        if (
            not isinstance(raw_row, Sequence)
            or isinstance(raw_row, (str, bytes))
            or len(raw_row) != 5
        ):
            raise CollectorError("Deribit DVOL candle must contain 5 values")
        row = {
            "timestamp": _unix_seconds_from_milliseconds(raw_row[0]),
            "open": _float(raw_row[1], label="DVOL open"),
            "high": _float(raw_row[2], label="DVOL high"),
            "low": _float(raw_row[3], label="DVOL low"),
            "close": _float(raw_row[4], label="DVOL close"),
        }
        _merge_row(by_timestamp, row)

    continuation_raw = result.get("continuation")
    continuation = (
        None
        if continuation_raw is None
        else _integer(continuation_raw, label="continuation")
    )
    return [by_timestamp[ts] for ts in sorted(by_timestamp)], continuation


def fetch_dvol_candles(
    currency: str,
    *,
    start_timestamp_ms: int,
    end_timestamp_ms: int,
    resolution: str = "1D",
    fetcher: HttpFetcherFn = default_http_fetcher,
    max_pages: int = DEFAULT_MAX_PAGES,
    pause_seconds: float = DEFAULT_PAGE_PAUSE_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch a half-open DVOL window ``[start_timestamp_ms, end_timestamp_ms)``.

    Pagination is fail-closed: a continuation must remain inside the requested
    window and move the backwards cursor strictly earlier on every page.
    Identical boundary rows are deduplicated; conflicting duplicates fail.
    """

    if not isinstance(currency, str) or currency not in SUPPORTED_CURRENCIES:
        raise ValueError(f"unsupported Deribit DVOL currency: {currency!r}")
    if resolution not in SUPPORTED_RESOLUTIONS:
        raise ValueError(f"unsupported Deribit DVOL resolution: {resolution!r}")
    if (
        isinstance(start_timestamp_ms, bool)
        or not isinstance(start_timestamp_ms, int)
        or isinstance(end_timestamp_ms, bool)
        or not isinstance(end_timestamp_ms, int)
        or start_timestamp_ms < 0
        or end_timestamp_ms <= start_timestamp_ms
    ):
        raise ValueError("invalid Deribit DVOL time window")
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages <= 0:
        raise ValueError("max_pages must be a positive integer")
    if pause_seconds < 0:
        raise ValueError("pause_seconds must be non-negative")

    cursor = end_timestamp_ms
    by_timestamp: dict[int, dict[str, Any]] = {}

    for page in range(max_pages):
        payload = fetcher(
            DERIBIT_DVOL_URL,
            {
                "currency": currency,
                "start_timestamp": start_timestamp_ms,
                "end_timestamp": cursor,
                "resolution": resolution,
            },
        )
        if not isinstance(payload, Mapping):
            raise CollectorError("Deribit DVOL response is not an object")
        rows, continuation = parse_dvol_page(payload)
        for row in rows:
            timestamp_ms = int(row["timestamp"]) * 1000
            if start_timestamp_ms <= timestamp_ms < end_timestamp_ms:
                _merge_row(by_timestamp, row)

        if continuation is None:
            ordered = [by_timestamp[ts] for ts in sorted(by_timestamp)]
            if any(
                int(left["timestamp"]) >= int(right["timestamp"])
                for left, right in zip(ordered, ordered[1:], strict=False)
            ):
                raise CollectorError("Deribit DVOL output timestamps are not strict")
            return ordered
        if not rows:
            raise CollectorError(
                "Deribit DVOL pagination returned a continuation but no rows"
            )
        if continuation < start_timestamp_ms or continuation >= cursor:
            raise CollectorError(
                "Deribit DVOL pagination cursor did not move strictly backwards"
            )
        cursor = continuation
        if page + 1 < max_pages and pause_seconds > 0:
            time.sleep(pause_seconds)

    raise CollectorError(f"Deribit DVOL exceeded max_pages={max_pages}")
