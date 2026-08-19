"""Binance USDT-M futures public derivatives feeds (no auth).

Sources (documented, free)
--------------------------
- Funding: ``GET https://fapi.binance.com/fapi/v1/fundingRate``
- Open interest: ``GET https://fapi.binance.com/futures/data/openInterestHist``

Liquidations
------------
``GET /fapi/v1/allForceOrders`` only exposes a short rolling window and is
not suitable for long-horizon event studies. Phase 26 marks liquidations as
``blocked_data`` until a stable historical source is integrated.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._common import (
    DEFAULT_COLLECTOR_CACHE_DIR,
    CollectorError,
    default_http_fetcher,
    load_json_cache,
    save_json_cache,
    utc_now_iso,
)
from .binance_public import normalize_binance_symbol

BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI_HIST_URL = "https://fapi.binance.com/futures/data/openInterestHist"

FUNDING_CACHE_SOURCE = "binance_fapi_funding_rate"
OI_CACHE_SOURCE = "binance_fapi_open_interest_hist"

FUNDING_PAGE_LIMIT = 1000
OI_PAGE_LIMIT = 500
# Binance openInterestHist rejects very old startTime (≈30d effective window).
MAX_OI_LOOKBACK_DAYS = 30
BINANCE_SLEEP_BETWEEN_PAGES_SECONDS = 0.2

OI_PERIODS = frozenset({"5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"})

# Phase 26 timeframes map to Binance OI period strings.
TIMEFRAME_TO_OI_PERIOD: dict[str, str] = {
    "4h": "4h",
    "1d": "1d",
}

LIQUIDATIONS_STATUS = "blocked_data"
LIQUIDATIONS_BLOCKED_REASON = (
    "Binance /fapi/v1/allForceOrders is a short rolling window only; "
    "no stable public historical liquidation series in repo."
)

BinanceFetcherFn = Callable[[str, Mapping[str, Any]], Any]


def futures_symbol(ticker: str) -> str:
    """USDT-M perpetual symbol (e.g. BTCUSDT)."""
    return normalize_binance_symbol(ticker)


def default_funding_cache_path(ticker: str, cache_dir: Path | None = None) -> Path:
    sym = ticker.strip().upper().partition("/")[0]
    root = cache_dir or DEFAULT_COLLECTOR_CACHE_DIR
    return root / f"funding_{sym}.json"


def default_oi_cache_path(
    ticker: str,
    period: str,
    cache_dir: Path | None = None,
) -> Path:
    sym = ticker.strip().upper().partition("/")[0]
    p = period.strip().lower()
    root = cache_dir or DEFAULT_COLLECTOR_CACHE_DIR
    return root / f"oi_{sym}_{p}.json"


def _normalize_funding_row(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    ts = raw.get("fundingTime") or raw.get("timestamp")
    rate = raw.get("fundingRate") if raw.get("fundingRate") is not None else raw.get("funding_rate")
    if ts is None or rate is None:
        return None
    try:
        ts_i = int(ts)
        if ts_i > 10_000_000_000:
            ts_i //= 1000
        rate_f = float(rate)
    except (TypeError, ValueError):
        return None
    return {
        "timestamp": ts_i,
        "funding_rate": rate_f,
        "symbol": str(raw.get("symbol", "")),
    }


def _normalize_oi_row(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    ts = raw.get("timestamp")
    oi = raw.get("sumOpenInterest") if raw.get("sumOpenInterest") is not None else raw.get("open_interest")
    if ts is None or oi is None:
        return None
    try:
        ts_i = int(ts)
        if ts_i > 10_000_000_000:
            ts_i //= 1000
        oi_f = float(oi)
    except (TypeError, ValueError):
        return None
    if oi_f < 0:
        return None
    val = raw.get("sumOpenInterestValue")
    oi_usd = float(val) if val is not None else None
    return {
        "timestamp": ts_i,
        "open_interest": oi_f,
        "open_interest_value_usd": oi_usd,
        "symbol": str(raw.get("symbol", "")),
    }


def parse_funding_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in rows:
        row = _normalize_funding_row(raw)
        if row is None:
            continue
        ts = int(row["timestamp"])
        if ts in seen:
            continue
        seen.add(ts)
        out.append(row)
    out.sort(key=lambda r: int(r["timestamp"]))
    return out


def parse_oi_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in rows:
        row = _normalize_oi_row(raw)
        if row is None:
            continue
        ts = int(row["timestamp"])
        if ts in seen:
            continue
        seen.add(ts)
        out.append(row)
    out.sort(key=lambda r: int(r["timestamp"]))
    return out


def load_derivatives_cache(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load cache file; return (rows, meta). Missing file → empty rows."""
    payload = load_json_cache(path)
    if not payload:
        return [], {"status": "blocked_data", "blocked_reason": "cache file missing"}
    entries = payload.get("entries") or {}
    raw = entries.get("rows") if isinstance(entries, dict) else None
    if not isinstance(raw, list):
        raw = payload.get("rows")
    if not isinstance(raw, list):
        return [], {"status": "blocked_data", "blocked_reason": "missing entries.rows"}
    kind = str(payload.get("kind", ""))
    if kind == "funding":
        rows = parse_funding_rows(raw)
    elif kind == "open_interest":
        rows = parse_oi_rows(raw)
    else:
        rows = parse_funding_rows(raw) if "funding" in path.name else parse_oi_rows(raw)
    meta = {
        "status": "available" if rows else "blocked_data",
        "source": payload.get("source"),
        "symbol": payload.get("symbol"),
        "period": payload.get("period"),
        "row_count": len(rows),
        "fetched_at": payload.get("fetched_at"),
    }
    if not rows:
        meta["blocked_reason"] = "empty rows after parse"
    return rows, meta


def save_funding_cache(
    path: Path,
    *,
    ticker: str,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    parsed = parse_funding_rows(rows)
    sym = futures_symbol(ticker)
    save_json_cache(
        path,
        {
            "source": FUNDING_CACHE_SOURCE,
            "kind": "funding",
            "symbol": sym,
            "ticker": ticker.strip().upper().partition("/")[0],
            "fetched_at": utc_now_iso(),
            "entries": {"rows": parsed},
        },
    )


def save_oi_cache(
    path: Path,
    *,
    ticker: str,
    period: str,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    parsed = parse_oi_rows(rows)
    p = period.strip().lower()
    sym = futures_symbol(ticker)
    save_json_cache(
        path,
        {
            "source": OI_CACHE_SOURCE,
            "kind": "open_interest",
            "symbol": sym,
            "period": p,
            "ticker": ticker.strip().upper().partition("/")[0],
            "fetched_at": utc_now_iso(),
            "entries": {"rows": parsed},
        },
    )


def fetch_funding_rate_history(
    ticker: str,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    fetcher: BinanceFetcherFn = default_http_fetcher,
) -> list[dict[str, Any]]:
    """Paginated funding history (newest page first per Binance API)."""
    sym = futures_symbol(ticker)
    all_rows: list[dict[str, Any]] = []
    cursor_end = end_ms
    while True:
        params: dict[str, Any] = {"symbol": sym, "limit": FUNDING_PAGE_LIMIT}
        if start_ms is not None:
            params["startTime"] = start_ms
        if cursor_end is not None:
            params["endTime"] = cursor_end
        data = fetcher(BINANCE_FUNDING_URL, params)
        if not isinstance(data, list):
            raise CollectorError(f"unexpected funding payload: {type(data).__name__}")
        if not data:
            break
        batch = parse_funding_rows(data)
        if not batch:
            break
        oldest_ts = min(int(r["timestamp"]) for r in batch)
        all_rows = batch + all_rows
        if len(data) < FUNDING_PAGE_LIMIT:
            break
        if start_ms is not None and oldest_ts * 1000 <= start_ms:
            break
        cursor_end = oldest_ts * 1000 - 1
        time.sleep(BINANCE_SLEEP_BETWEEN_PAGES_SECONDS)
    # Dedupe after merge
    return parse_funding_rows(all_rows)


def _clamp_oi_start_ms(start_ms: int | None, end_ms: int | None) -> int | None:
    if start_ms is None:
        return None
    import time as _time

    end = end_ms if end_ms is not None else int(_time.time() * 1000)
    max_span_ms = MAX_OI_LOOKBACK_DAYS * 86400 * 1000
    floor = end - max_span_ms
    return max(start_ms, floor)


def fetch_open_interest_history(
    ticker: str,
    period: str,
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
    fetcher: BinanceFetcherFn = default_http_fetcher,
) -> list[dict[str, Any]]:
    p = period.strip().lower()
    if p not in OI_PERIODS:
        raise ValueError(f"unsupported OI period: {period}")
    sym = futures_symbol(ticker)
    all_rows: list[dict[str, Any]] = []
    cursor_start = _clamp_oi_start_ms(start_ms, end_ms)
    while True:
        params: dict[str, Any] = {
            "symbol": sym,
            "period": p,
            "limit": OI_PAGE_LIMIT,
        }
        if cursor_start is not None:
            params["startTime"] = cursor_start
        if end_ms is not None:
            params["endTime"] = end_ms
        try:
            data = fetcher(BINANCE_OI_HIST_URL, params)
        except CollectorError:
            if cursor_start is not None:
                params.pop("startTime", None)
                data = fetcher(BINANCE_OI_HIST_URL, params)
            else:
                raise
        if not isinstance(data, list):
            raise CollectorError(f"unexpected OI payload: {type(data).__name__}")
        if not data:
            break
        batch = parse_oi_rows(data)
        if not batch:
            break
        all_rows.extend(batch)
        if len(data) < OI_PAGE_LIMIT:
            break
        newest_ts = max(int(r["timestamp"]) for r in batch)
        next_start = newest_ts * 1000 + 1
        if cursor_start is not None and next_start <= cursor_start:
            break
        cursor_start = next_start
        time.sleep(BINANCE_SLEEP_BETWEEN_PAGES_SECONDS)
    return parse_oi_rows(all_rows)


def ms_from_unix(ts: int) -> int:
    return int(ts) * 1000


def unix_from_iso_date(d: str) -> int:
    dt = datetime.fromisoformat(d).replace(tzinfo=UTC)
    return int(dt.timestamp())


def audit_derivatives_readiness(
    tickers: Sequence[str],
    *,
    cache_dir: Path | None = None,
    oi_periods: Sequence[str] = ("4h", "1d"),
    min_funding_rows: int = 100,
    min_oi_rows: int = 100,
) -> dict[str, Any]:
    """Build readiness manifest for Phase 26A."""
    root = cache_dir or DEFAULT_COLLECTOR_CACHE_DIR
    entries: list[dict[str, Any]] = []
    for ticker in tickers:
        sym = ticker.strip().upper().partition("/")[0]
        fpath = default_funding_cache_path(sym, root)
        f_rows, f_meta = load_derivatives_cache(fpath)
        f_ok = len(f_rows) >= min_funding_rows
        entries.append(
            {
                "asset": sym,
                "series": "funding",
                "path": str(fpath),
                "status": "available" if f_ok else f_meta.get("status", "blocked_data"),
                "row_count": len(f_rows),
                "blocked_reason": None if f_ok else f_meta.get("blocked_reason"),
            }
        )
        for period in oi_periods:
            opath = default_oi_cache_path(sym, period, root)
            o_rows, o_meta = load_derivatives_cache(opath)
            o_ok = len(o_rows) >= min_oi_rows
            entries.append(
                {
                    "asset": sym,
                    "series": f"open_interest_{period}",
                    "path": str(opath),
                    "status": "available" if o_ok else o_meta.get("status", "blocked_data"),
                    "row_count": len(o_rows),
                    "blocked_reason": None if o_ok else o_meta.get("blocked_reason"),
                }
            )
    entries.append(
        {
            "asset": "*",
            "series": "liquidations",
            "path": "",
            "status": LIQUIDATIONS_STATUS,
            "row_count": 0,
            "blocked_reason": LIQUIDATIONS_BLOCKED_REASON,
        }
    )
    available = sum(1 for e in entries if e.get("status") == "available")
    return {
        "generated_at": utc_now_iso(),
        "cache_root": str(root),
        "entries": entries,
        "available_count": available,
        "entries_total": len(entries),
        "liquidations": {
            "status": LIQUIDATIONS_STATUS,
            "reason": LIQUIDATIONS_BLOCKED_REASON,
        },
    }
