"""Public Kraken Futures Charts collectors (no authentication).

The Charts API exposes venue-native candles and microstructure analytics.  It
caps responses and advertises continuation with ``more`` / ``more_candles``;
callers must therefore advance the lower time bound explicitly.  All returned
timestamps are normalised to UTC unix seconds.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from ._common import CollectorError, HttpFetcherFn, default_http_fetcher

CHARTS_BASE_URL = "https://futures.kraken.com/api/charts/v1"

SUPPORTED_RESOLUTIONS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "12h": 43200,
    "1d": 86400,
}

SUPPORTED_ANALYTICS = frozenset(
    {
        "open-interest",
        "aggressor-differential",
        "liquidation-volume",
        "cvd",
        "funding",
        "future-basis",
        "slippage",
    }
)

SCALAR_ANALYTICS = frozenset({"aggressor-differential", "liquidation-volume"})
OHLC_ANALYTICS = frozenset({"open-interest"})
DEFAULT_MAX_PAGES = 500
DEFAULT_PAGE_PAUSE_SECONDS = 0.05


def _unix_seconds(value: Any) -> int:
    try:
        ts = int(value)
    except (TypeError, ValueError) as exc:
        raise CollectorError(f"invalid Kraken Charts timestamp: {value!r}") from exc
    if ts > 10_000_000_000:
        ts //= 1000
    return ts


def _float(value: Any, *, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise CollectorError(f"invalid {label}: {value!r}") from exc


def parse_candles_page(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    raw = payload.get("candles")
    if not isinstance(raw, list):
        raise CollectorError("Kraken Charts candles payload is missing candles[]")

    by_timestamp: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise CollectorError("Kraken Charts candle is not an object")
        ts = _unix_seconds(item.get("time"))
        by_timestamp[ts] = {
            "timestamp": ts,
            "open": _float(item.get("open"), label="candle open"),
            "high": _float(item.get("high"), label="candle high"),
            "low": _float(item.get("low"), label="candle low"),
            "close": _float(item.get("close"), label="candle close"),
            "volume": _float(item.get("volume", 0), label="candle volume"),
        }
    return [by_timestamp[ts] for ts in sorted(by_timestamp)], bool(
        payload.get("more_candles", False)
    )


def _analytics_result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise CollectorError("Kraken Charts analytics payload is missing result")
    return result


def parse_analytics_page(
    analytics_type: str,
    payload: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    if analytics_type not in SUPPORTED_ANALYTICS:
        raise ValueError(f"unsupported Kraken analytics type: {analytics_type}")
    result = _analytics_result(payload)
    raw_timestamps = result.get("timestamp")
    if not isinstance(raw_timestamps, list):
        raise CollectorError("Kraken Charts analytics result is missing timestamp[]")
    timestamps = [_unix_seconds(value) for value in raw_timestamps]
    data = result.get("data")

    rows: list[dict[str, Any]] = []
    if analytics_type in SCALAR_ANALYTICS:
        if not isinstance(data, list) or len(data) != len(timestamps):
            raise CollectorError(
                f"{analytics_type} data length does not match timestamps"
            )
        field = analytics_type.replace("-", "_")
        for ts, value in zip(timestamps, data, strict=True):
            rows.append({"timestamp": ts, field: _float(value, label=field)})
    elif analytics_type in OHLC_ANALYTICS:
        if not isinstance(data, list) or len(data) != len(timestamps):
            raise CollectorError(
                f"{analytics_type} data length does not match timestamps"
            )
        prefix = analytics_type.replace("-", "_")
        for ts, value in zip(timestamps, data, strict=True):
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise CollectorError(f"{analytics_type} row is not OHLC")
            if len(value) != 4:
                raise CollectorError(f"{analytics_type} OHLC row must contain 4 values")
            rows.append(
                {
                    "timestamp": ts,
                    f"{prefix}_open": _float(value[0], label=f"{prefix} open"),
                    f"{prefix}_high": _float(value[1], label=f"{prefix} high"),
                    f"{prefix}_low": _float(value[2], label=f"{prefix} low"),
                    f"{prefix}_close": _float(value[3], label=f"{prefix} close"),
                }
            )
    else:
        # Rich diagnostics are preserved as JSON-compatible rows.  The research
        # signal does not depend on these feeds, so their nested schema remains
        # explicit instead of being guessed into scalar fields.
        if not isinstance(data, Mapping):
            raise CollectorError(f"{analytics_type} data is not an object")
        for index, ts in enumerate(timestamps):
            row: dict[str, Any] = {"timestamp": ts}
            for key, values in data.items():
                if isinstance(values, list) and len(values) == len(timestamps):
                    row[str(key)] = values[index]
            rows.append(row)

    by_timestamp = {int(row["timestamp"]): row for row in rows}
    return [by_timestamp[ts] for ts in sorted(by_timestamp)], bool(
        result.get("more", False)
    )


def _validate_window(since: int, to: int, interval_seconds: int) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    if since < 0 or to <= since:
        raise ValueError("invalid Kraken Charts time window")


def fetch_candles(
    symbol: str,
    resolution: str,
    *,
    since: int,
    to: int,
    tick_type: str = "trade",
    fetcher: HttpFetcherFn = default_http_fetcher,
    max_pages: int = DEFAULT_MAX_PAGES,
    pause_seconds: float = DEFAULT_PAGE_PAUSE_SECONDS,
) -> list[dict[str, Any]]:
    if resolution not in SUPPORTED_RESOLUTIONS:
        raise ValueError(f"unsupported Kraken Charts resolution: {resolution}")
    interval_seconds = SUPPORTED_RESOLUTIONS[resolution]
    _validate_window(since, to, interval_seconds)
    url = f"{CHARTS_BASE_URL}/{tick_type}/{symbol}/{resolution}"
    cursor = int(since)
    by_timestamp: dict[int, dict[str, Any]] = {}

    for page in range(max_pages):
        payload = fetcher(url, {"from": cursor, "to": int(to)})
        if not isinstance(payload, Mapping):
            raise CollectorError("Kraken Charts candles response is not an object")
        rows, more = parse_candles_page(payload)
        for row in rows:
            ts = int(row["timestamp"])
            if since <= ts < to:
                by_timestamp[ts] = row
        if not more:
            return [by_timestamp[ts] for ts in sorted(by_timestamp)]
        if not rows:
            raise CollectorError("Kraken Charts candles pagination returned more=true but no rows")
        next_cursor = max(int(row["timestamp"]) for row in rows) + interval_seconds
        if next_cursor <= cursor:
            raise CollectorError("Kraken Charts candles pagination cursor did not advance")
        cursor = next_cursor
        if page + 1 < max_pages and pause_seconds > 0:
            time.sleep(pause_seconds)

    raise CollectorError(f"Kraken Charts candles exceeded max_pages={max_pages}")


def fetch_analytics(
    symbol: str,
    analytics_type: str,
    *,
    interval_seconds: int,
    since: int,
    to: int,
    fetcher: HttpFetcherFn = default_http_fetcher,
    max_pages: int = DEFAULT_MAX_PAGES,
    pause_seconds: float = DEFAULT_PAGE_PAUSE_SECONDS,
) -> list[dict[str, Any]]:
    if analytics_type not in SUPPORTED_ANALYTICS:
        raise ValueError(f"unsupported Kraken analytics type: {analytics_type}")
    if interval_seconds not in SUPPORTED_RESOLUTIONS.values():
        raise ValueError(f"unsupported Kraken analytics interval: {interval_seconds}")
    _validate_window(since, to, interval_seconds)
    url = f"{CHARTS_BASE_URL}/analytics/{symbol}/{analytics_type}"
    cursor = int(since)
    by_timestamp: dict[int, dict[str, Any]] = {}

    for page in range(max_pages):
        payload = fetcher(
            url,
            {"since": cursor, "to": int(to), "interval": interval_seconds},
        )
        if not isinstance(payload, Mapping):
            raise CollectorError("Kraken Charts analytics response is not an object")
        rows, more = parse_analytics_page(analytics_type, payload)
        for row in rows:
            ts = int(row["timestamp"])
            if since <= ts < to:
                by_timestamp[ts] = row
        if not more:
            return [by_timestamp[ts] for ts in sorted(by_timestamp)]
        if not rows:
            raise CollectorError(
                f"Kraken Charts {analytics_type} pagination returned more=true but no rows"
            )
        next_cursor = max(int(row["timestamp"]) for row in rows) + interval_seconds
        if next_cursor <= cursor:
            raise CollectorError(
                f"Kraken Charts {analytics_type} pagination cursor did not advance"
            )
        cursor = next_cursor
        if page + 1 < max_pages and pause_seconds > 0:
            time.sleep(pause_seconds)

    raise CollectorError(
        f"Kraken Charts {analytics_type} exceeded max_pages={max_pages}"
    )
