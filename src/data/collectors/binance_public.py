"""Binance public klines + local OHLC cache for long event-study windows.

Sources (free, no auth)
-----------------------
- Klines: ``https://api.binance.com/api/v3/klines``

Local cache (``data/collector_cache/ohlc_daily_{TICKER}.json``) holds
daily candles for offline / CI runs when Kraken's ~720-candle REST cap
is insufficient.

Normalized rows match :func:`scripts._event_study_common.fetch_daily_ohlc`:

- ``timestamp`` (int): UTC unix seconds at day boundary
- ``open``, ``high``, ``low``, ``close``, ``vwap``, ``volume`` (float)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ._common import (
    DEFAULT_COLLECTOR_CACHE_DIR,
    CollectorError,
    default_http_fetcher,
    filter_rows_by_date_range,
    load_json_cache,
    parse_iso_date,
    save_json_cache,
    utc_now_iso,
)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_KLINES_MAX_LIMIT = 1000
BINANCE_SLEEP_BETWEEN_PAGES_SECONDS = 0.2

# Bare ticker → Binance spot symbol (USDT quote).
CRYPTO_TICKER_TO_BINANCE_SYMBOL: dict[str, str] = {
    "BTC": "BTCUSDT",
    "XBT": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "AVAX": "AVAXUSDT",
    "LTC": "LTCUSDT",
    "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT",
    "LINK": "LINKUSDT",
    "ADA": "ADAUSDT",
    "DOT": "DOTUSDT",
}

OHLC_CACHE_SOURCE = "ohlc_daily_cache"

BinanceFetcherFn = Callable[[str, Mapping[str, Any]], Any]


def normalize_binance_symbol(ticker_or_pair: str) -> str:
    """Map bare ticker or slash pair to Binance ``SYMBOL`` (e.g. ``BTCUSDT``)."""
    if not ticker_or_pair:
        raise ValueError("ticker_or_pair must be non-empty")
    raw = ticker_or_pair.strip().upper()
    head, _, _ = raw.partition("/")
    if head in CRYPTO_TICKER_TO_BINANCE_SYMBOL:
        return CRYPTO_TICKER_TO_BINANCE_SYMBOL[head]
    if raw.endswith("USDT"):
        return raw.replace("/", "")
    if "/" in raw:
        base, _, quote = raw.partition("/")
        if quote in ("USD", "USDT"):
            return f"{base}USDT"
    return f"{head}USDT"


def default_ohlc_daily_cache_path(ticker: str) -> Path:
    """Default path: ``data/collector_cache/ohlc_daily_{TICKER}.json``."""
    sym = ticker.strip().upper().partition("/")[0]
    return DEFAULT_COLLECTOR_CACHE_DIR / f"ohlc_daily_{sym}.json"


def _normalize_candle_row(
    raw: Mapping[str, Any],
    *,
    normalize_to_day: bool = True,
) -> dict[str, Any] | None:
    ts = raw.get("timestamp")
    if not isinstance(ts, int):
        return None
    try:
        o = float(raw["open"])
        h = float(raw["high"])
        lo = float(raw["low"])
        c = float(raw["close"])
        vol = float(raw["volume"])
    except (KeyError, TypeError, ValueError):
        return None
    if vol < 0 or o <= 0 or h <= 0 or lo <= 0 or c <= 0:
        return None
    vwap_raw = raw.get("vwap")
    if vwap_raw is not None:
        try:
            vwap = float(vwap_raw)
        except (TypeError, ValueError):
            vwap = (h + lo + c) / 3.0
    else:
        vwap = (h + lo + c) / 3.0
    if normalize_to_day:
        d = datetime.fromtimestamp(ts, tz=UTC).date()
        ts_norm = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())
    else:
        ts_norm = ts
    return {
        "timestamp": ts_norm,
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "vwap": vwap,
        "volume": vol,
    }


def parse_ohlc_candle_rows(
    rows: Any,
    *,
    normalize_to_day: bool = True,
) -> list[dict[str, Any]]:
    """Parse candle dicts; daily caches normalize to UTC midnight."""
    if not isinstance(rows, list):
        raise CollectorError(
            f"OHLC candle payload is not a list: {type(rows).__name__}"
        )
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        row = _normalize_candle_row(item, normalize_to_day=normalize_to_day)
        if row is not None:
            out.append(row)
    out.sort(key=lambda r: int(r["timestamp"]))
    return out


def parse_binance_klines(payload: Any) -> list[dict[str, Any]]:
    """Parse Binance ``/api/v3/klines`` JSON array into normalized rows."""
    if not isinstance(payload, list):
        raise CollectorError(
            f"Binance klines payload is not a list: {type(payload).__name__}"
        )
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, list) or len(item) < 6:
            continue
        try:
            open_ms = int(item[0])
            o = float(item[1])
            h = float(item[2])
            lo = float(item[3])
            c = float(item[4])
            vol = float(item[5])
        except (TypeError, ValueError):
            continue
        ts = open_ms // 1000
        d = datetime.fromtimestamp(ts, tz=UTC).date()
        ts_norm = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())
        quote_vol = float(item[7]) if len(item) > 7 else 0.0
        vwap = quote_vol / vol if vol > 0 else (h + lo + c) / 3.0
        rows.append(
            {
                "timestamp": ts_norm,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "vwap": vwap,
                "volume": vol,
            }
        )
    rows.sort(key=lambda r: int(r["timestamp"]))
    return rows


def _merge_candles_by_timestamp(
    existing: Sequence[dict[str, Any]],
    fresh: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_ts: dict[int, dict[str, Any]] = {
        int(r["timestamp"]): dict(r) for r in existing if isinstance(r.get("timestamp"), int)
    }
    for row in fresh:
        ts = row.get("timestamp")
        if isinstance(ts, int):
            by_ts[ts] = dict(row)
    return sorted(by_ts.values(), key=lambda r: int(r["timestamp"]))


def _min_rows_for_days(days: int) -> int:
    return max(int(days), 30)


def _date_range_for_days(days: int) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=max(days, 1) + 5)
    return start, today


def load_ohlc_daily_cache(
    cache_path: Path,
    *,
    ticker: str,
    start: date,
    end: date,
    min_rows: int,
) -> list[dict[str, Any]]:
    """Load normalized candles from ``ohlc_daily_{TICKER}.json``."""
    payload = load_json_cache(cache_path)
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        raise CollectorError(f"OHLC cache {cache_path} missing entries")
    raw_candles = entries.get("candles")
    rows = parse_ohlc_candle_rows(raw_candles)
    filtered = filter_rows_by_date_range(list(rows), start=start, end=end)
    if len(filtered) < min_rows:
        raise CollectorError(
            f"OHLC cache {cache_path} incomplete for {start.isoformat()}.."
            f"{end.isoformat()} (have {len(filtered)} rows in window, need >={min_rows})"
        )
    return filtered


def save_ohlc_daily_cache(
    cache_path: Path,
    *,
    ticker: str,
    rows: Sequence[dict[str, Any]],
    source: str = OHLC_CACHE_SOURCE,
) -> None:
    sym = ticker.strip().upper().partition("/")[0]
    save_json_cache(
        cache_path,
        {
            "source": source,
            "generated_at": utc_now_iso(),
            "ticker": sym,
            "interval_minutes": 1440,
            "entries": {"candles": list(rows)},
        },
    )


def fetch_binance_daily_klines(
    ticker: str,
    *,
    days: int,
    fetcher: BinanceFetcherFn = default_http_fetcher,
    sleep_between_pages: float = BINANCE_SLEEP_BETWEEN_PAGES_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch daily klines from Binance public REST (paginated, read-only)."""
    import time

    symbol = normalize_binance_symbol(ticker)
    start_date, end_date = _date_range_for_days(days)
    start_ms = int(
        datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=UTC
        ).timestamp()
        * 1000
    )
    end_ms = int(
        datetime(
            end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=UTC
        ).timestamp()
        * 1000
    )

    all_rows: list[dict[str, Any]] = []
    cursor_ms = start_ms
    pages = 0
    max_pages = max(10, (days // BINANCE_KLINES_MAX_LIMIT) + 3)

    while cursor_ms <= end_ms and pages < max_pages:
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": "1d",
            "startTime": cursor_ms,
            "endTime": end_ms,
            "limit": BINANCE_KLINES_MAX_LIMIT,
        }
        payload = fetcher(BINANCE_KLINES_URL, params)
        page_rows = parse_binance_klines(payload)
        if not page_rows:
            break
        all_rows = _merge_candles_by_timestamp(all_rows, page_rows)
        last_ts = int(page_rows[-1]["timestamp"])
        next_ms = (last_ts + 86400) * 1000
        if next_ms <= cursor_ms:
            break
        cursor_ms = next_ms
        pages += 1
        if pages < max_pages and cursor_ms <= end_ms:
            time.sleep(sleep_between_pages)

    merged = _merge_candles_by_timestamp([], all_rows)
    min_rows = _min_rows_for_days(days)
    filtered = filter_rows_by_date_range(merged, start=start_date, end=end_date)
    if len(filtered) < min_rows:
        raise CollectorError(
            f"Binance klines for {symbol} returned only {len(filtered)} daily rows "
            f"(expected >={min_rows})"
        )
    return filtered


def fetch_ohlc_daily_with_cache(
    ticker: str,
    days: int,
    *,
    cache_path: Path | None = None,
    use_cache_only: bool = False,
    fetcher: BinanceFetcherFn = default_http_fetcher,
) -> list[dict[str, Any]]:
    """Load OHLC from disk cache or fetch Binance and persist."""
    path = cache_path or default_ohlc_daily_cache_path(ticker)
    start, end = _date_range_for_days(days)
    min_rows = _min_rows_for_days(days)

    if path.exists():
        try:
            rows = load_ohlc_daily_cache(
                path, ticker=ticker, start=start, end=end, min_rows=min_rows
            )
            if rows:
                return rows
        except CollectorError:
            if use_cache_only:
                raise

    if use_cache_only:
        raise CollectorError(
            f"use_cache_only: OHLC cache missing or incomplete at {path}"
        )

    rows = fetch_binance_daily_klines(ticker, days=days, fetcher=fetcher)
    save_ohlc_daily_cache(path, ticker=ticker, rows=rows)
    return rows


def fetch_ohlc_daily_cache_only(
    ticker: str,
    days: int,
    *,
    cache_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load daily OHLC strictly from ``data/collector_cache/`` (no network)."""
    path = cache_path or default_ohlc_daily_cache_path(ticker)
    start, end = _date_range_for_days(days)
    min_rows = _min_rows_for_days(days)
    return load_ohlc_daily_cache(
        path, ticker=ticker, start=start, end=end, min_rows=min_rows
    )


def iso_window_to_dates(start_iso: str, end_iso: str) -> tuple[date, date]:
    """Parse ISO date strings for cache filtering."""
    start = parse_iso_date(start_iso)
    end = parse_iso_date(end_iso)
    if start is None or end is None:
        raise ValueError(f"invalid ISO window: {start_iso!r} .. {end_iso!r}")
    return start, end


# --- Intraday backbone (Phase 21): 1h / 4h / extended 1d ---

OHLC_INTRADAY_CACHE_SOURCE = "binance_public_klines"

TIMEFRAME_BINANCE_INTERVAL: dict[str, str] = {
    "1d": "1d",
    "4h": "4h",
    "1h": "1h",
}

TIMEFRAME_INTERVAL_MINUTES: dict[str, int] = {
    "1d": 1440,
    "4h": 240,
    "1h": 60,
}

TIMEFRAME_CACHE_BASENAME: dict[str, str] = {
    "1d": "ohlc_daily",
    "4h": "ohlc_4h",
    "1h": "ohlc_1h",
}

# Target history depth (calendar days) for cache fill.
TIMEFRAME_COVERAGE_DAYS: dict[str, int] = {
    "1d": 365 * 5,
    "4h": 365 * 3,
    "1h": 365 * 2,
}

# Minimum row counts for ``data_ok`` (Phase 21 readiness gate).
MIN_ROWS_DATA_OK: dict[str, int] = {
    "1d": 1800,
    "4h": 6000,
    "1h": 17000,
}


def default_ohlc_cache_path(ticker: str, timeframe: str) -> Path:
    """Path for ``ohlc_{tf}_{TICKER}.json`` under collector_cache."""
    tf = timeframe.strip().lower()
    if tf not in TIMEFRAME_CACHE_BASENAME:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    sym = ticker.strip().upper().partition("/")[0]
    basename = TIMEFRAME_CACHE_BASENAME[tf]
    return DEFAULT_COLLECTOR_CACHE_DIR / f"{basename}_{sym}.json"


def parse_binance_klines_intraday(payload: Any) -> list[dict[str, Any]]:
    """Parse klines keeping candle open time (no day-boundary normalization)."""
    if not isinstance(payload, list):
        raise CollectorError(
            f"Binance klines payload is not a list: {type(payload).__name__}"
        )
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, list) or len(item) < 6:
            continue
        try:
            open_ms = int(item[0])
            o = float(item[1])
            h = float(item[2])
            lo = float(item[3])
            c = float(item[4])
            vol = float(item[5])
        except (TypeError, ValueError):
            continue
        if vol < 0 or o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            continue
        ts = open_ms // 1000
        quote_vol = float(item[7]) if len(item) > 7 else 0.0
        vwap = quote_vol / vol if vol > 0 else (h + lo + c) / 3.0
        rows.append(
            {
                "timestamp": ts,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "vwap": vwap,
                "volume": vol,
            }
        )
    rows.sort(key=lambda r: int(r["timestamp"]))
    return rows


def _interval_step_seconds(timeframe: str) -> int:
    tf = timeframe.strip().lower()
    return TIMEFRAME_INTERVAL_MINUTES[tf] * 60


def _date_range_for_coverage_days(days: int) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=max(days, 1) + 5)
    return start, today


def save_ohlc_cache(
    cache_path: Path,
    *,
    ticker: str,
    timeframe: str,
    rows: Sequence[dict[str, Any]],
    source: str = OHLC_INTRADAY_CACHE_SOURCE,
) -> None:
    """Persist OHLC cache compatible with :mod:`src.bot.data_loader`."""
    tf = timeframe.strip().lower()
    sym = ticker.strip().upper().partition("/")[0]
    save_json_cache(
        cache_path,
        {
            "source": source,
            "generated_at": utc_now_iso(),
            "ticker": sym,
            "interval_minutes": TIMEFRAME_INTERVAL_MINUTES[tf],
            "entries": {"candles": list(rows)},
        },
    )


def load_ohlc_cache_rows(cache_path: Path) -> list[dict[str, Any]]:
    """Load all candles from cache file (no date window filter)."""
    payload = load_json_cache(cache_path)
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        raise CollectorError(f"OHLC cache {cache_path} missing entries")
    raw_candles = entries.get("candles")
    interval = payload.get("interval_minutes") if isinstance(payload, dict) else None
    try:
        interval_int = int(interval) if interval is not None else 1440
    except (TypeError, ValueError):
        interval_int = 1440
    normalize_to_day = interval_int >= 1440
    return parse_ohlc_candle_rows(raw_candles, normalize_to_day=normalize_to_day)


def fetch_binance_klines(
    ticker: str,
    timeframe: str,
    *,
    coverage_days: int | None = None,
    fetcher: BinanceFetcherFn = default_http_fetcher,
    sleep_between_pages: float = BINANCE_SLEEP_BETWEEN_PAGES_SECONDS,
) -> list[dict[str, Any]]:
    """Fetch paginated Binance public klines for 1h, 4h, or 1d."""
    import time

    tf = timeframe.strip().lower()
    if tf not in TIMEFRAME_BINANCE_INTERVAL:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    days = coverage_days if coverage_days is not None else TIMEFRAME_COVERAGE_DAYS[tf]
    symbol = normalize_binance_symbol(ticker)
    start_date, end_date = _date_range_for_coverage_days(days)
    start_ms = int(
        datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=UTC
        ).timestamp()
        * 1000
    )
    end_ms = int(
        datetime(
            end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=UTC
        ).timestamp()
        * 1000
    )
    step_sec = _interval_step_seconds(tf)
    candles_per_day = max(1, 86400 // step_sec)
    expected_rows = days * candles_per_day
    max_pages = max(10, (expected_rows // BINANCE_KLINES_MAX_LIMIT) + 5)

    all_rows: list[dict[str, Any]] = []
    cursor_ms = start_ms
    pages = 0
    parse_fn = parse_binance_klines if tf == "1d" else parse_binance_klines_intraday

    while cursor_ms <= end_ms and pages < max_pages:
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": TIMEFRAME_BINANCE_INTERVAL[tf],
            "startTime": cursor_ms,
            "endTime": end_ms,
            "limit": BINANCE_KLINES_MAX_LIMIT,
        }
        payload = fetcher(BINANCE_KLINES_URL, params)
        page_rows = parse_fn(payload)
        if not page_rows:
            break
        all_rows = _merge_candles_by_timestamp(all_rows, page_rows)
        last_ts = int(page_rows[-1]["timestamp"])
        next_ms = (last_ts + step_sec) * 1000
        if next_ms <= cursor_ms:
            break
        cursor_ms = next_ms
        pages += 1
        if pages < max_pages and cursor_ms <= end_ms:
            time.sleep(sleep_between_pages)

    merged = _merge_candles_by_timestamp([], all_rows)
    expected_rows = days * candles_per_day
    min_rows = max(30, int(expected_rows * 0.85))
    if coverage_days is None:
        min_rows = max(min_rows, MIN_ROWS_DATA_OK.get(tf, min_rows))
    if len(merged) < min_rows:
        raise CollectorError(
            f"Binance klines for {symbol} {tf} returned {len(merged)} rows "
            f"(expected >={min_rows})"
        )
    return merged


def fetch_ohlc_with_cache(
    ticker: str,
    timeframe: str,
    *,
    cache_path: Path | None = None,
    use_cache_only: bool = False,
    coverage_days: int | None = None,
    fetcher: BinanceFetcherFn = default_http_fetcher,
) -> list[dict[str, Any]]:
    """Load OHLC from disk or fetch Binance public API and persist."""
    tf = timeframe.strip().lower()
    path = cache_path or default_ohlc_cache_path(ticker, tf)
    min_rows = MIN_ROWS_DATA_OK.get(tf, 30)

    if path.exists():
        try:
            rows = load_ohlc_cache_rows(path)
            if len(rows) >= min_rows:
                return rows
        except CollectorError:
            if use_cache_only:
                raise

    if use_cache_only:
        raise CollectorError(
            f"use_cache_only: OHLC cache missing or incomplete at {path} "
            f"(need >={min_rows} rows)"
        )

    rows = fetch_binance_klines(
        ticker,
        tf,
        coverage_days=coverage_days,
        fetcher=fetcher,
    )
    save_ohlc_cache(path, ticker=ticker, timeframe=tf, rows=rows)
    return rows
