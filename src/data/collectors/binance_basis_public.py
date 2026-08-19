"""Binance spot vs USDT-M perp basis (public, no auth).

Sources
-------
- Spot klines: ``GET https://api.binance.com/api/v3/klines``
- Mark price klines: ``GET https://fapi.binance.com/fapi/v1/markPriceKlines``

Derived fields (aligned to candle open timestamps):
- ``spot_price``, ``perp_price`` (close of each 4h bar)
- ``basis_pct`` = perp / spot - 1
- ``basis_zscore`` rolling z-score of basis_pct
- ``basis_z_status`` ``ok`` / ``warmup`` / ``no_data`` / ``flat`` (cf. :mod:`src.zscore`)
- ``basis_compression`` contracting elevated basis (|z| was >1, |basis| shrinking)
- ``basis_extreme`` |basis_zscore| >= extreme threshold
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...zscore import ZStatus, rolling_z_status
from ._common import (
    DEFAULT_COLLECTOR_CACHE_DIR,
    CollectorError,
    default_http_fetcher,
    load_json_cache,
    save_json_cache,
    utc_now_iso,
)
from .binance_derivatives_public import futures_symbol
from .binance_public import (
    BINANCE_SLEEP_BETWEEN_PAGES_SECONDS,
    TIMEFRAME_BINANCE_INTERVAL,
    TIMEFRAME_COVERAGE_DAYS,
    _date_range_for_coverage_days,
    _interval_step_seconds,
    _merge_candles_by_timestamp,
    fetch_binance_klines,
)

BINANCE_MARK_PRICE_KLINES_URL = "https://fapi.binance.com/fapi/v1/markPriceKlines"
BASIS_CACHE_SOURCE = "binance_spot_mark_basis"
BASIS_Z_WINDOW = 60
BASIS_EXTREME_Z = 2.0

BinanceFetcherFn = Callable[[str, Mapping[str, Any]], Any]


def default_basis_cache_path(
    ticker: str,
    timeframe: str = "4h",
    cache_dir: Path | None = None,
) -> Path:
    sym = ticker.strip().upper().partition("/")[0]
    tf = timeframe.strip().lower()
    root = cache_dir or DEFAULT_COLLECTOR_CACHE_DIR
    return root / f"basis_{sym}_{tf}.json"


def _parse_mark_price_klines(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise CollectorError(
            f"mark price klines payload is not a list: {type(payload).__name__}"
        )
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, list) or len(item) < 5:
            continue
        try:
            open_ms = int(item[0])
            c = float(item[4])
        except (TypeError, ValueError):
            continue
        if c <= 0:
            continue
        rows.append({"timestamp": open_ms // 1000, "close": c})
    rows.sort(key=lambda r: int(r["timestamp"]))
    return rows


def fetch_mark_price_klines(
    ticker: str,
    timeframe: str,
    *,
    coverage_days: int | None = None,
    fetcher: BinanceFetcherFn = default_http_fetcher,
) -> list[dict[str, Any]]:
    """Paginated futures mark-price klines (same interval as spot)."""
    tf = timeframe.strip().lower()
    if tf not in TIMEFRAME_BINANCE_INTERVAL:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    days = coverage_days if coverage_days is not None else TIMEFRAME_COVERAGE_DAYS[tf]
    symbol = futures_symbol(ticker)
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
    max_pages = max(10, (expected_rows // 1000) + 5)

    all_rows: list[dict[str, Any]] = []
    cursor_ms = start_ms
    pages = 0
    while cursor_ms <= end_ms and pages < max_pages:
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": TIMEFRAME_BINANCE_INTERVAL[tf],
            "startTime": cursor_ms,
            "endTime": end_ms,
            "limit": 1000,
        }
        payload = fetcher(BINANCE_MARK_PRICE_KLINES_URL, params)
        page_rows = _parse_mark_price_klines(payload)
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
            time.sleep(BINANCE_SLEEP_BETWEEN_PAGES_SECONDS)
    return sorted(all_rows, key=lambda r: int(r["timestamp"]))


def _basis_compression_flags(
    basis_pct: Sequence[float | None],
    basis_z: Sequence[float | None],
) -> list[bool]:
    out: list[bool] = []
    prev_abs: float | None = None
    # strict=True: rolling_z_status rend exactement un element par entree, les
    # deux sequences ont donc toujours la meme longueur. Toute divergence est
    # un bug d'alignement qu'on veut voir exploser ici, pas silencieusement
    # tronquer.
    for bp, bz in zip(basis_pct, basis_z, strict=True):
        if bp is None or bz is None:
            out.append(False)
            prev_abs = abs(bp) if bp is not None else prev_abs
            continue
        cur_abs = abs(bp)
        elevated = abs(bz) > 1.0 or (prev_abs is not None and prev_abs > 0.0005)
        contracting = prev_abs is not None and cur_abs < prev_abs * 0.85
        out.append(bool(elevated and contracting))
        prev_abs = cur_abs
    return out


def build_basis_rows(
    spot_rows: Sequence[Mapping[str, Any]],
    perp_rows: Sequence[Mapping[str, Any]],
    *,
    z_window: int = BASIS_Z_WINDOW,
    extreme_z: float = BASIS_EXTREME_Z,
) -> list[dict[str, Any]]:
    """Align spot/perp closes on timestamp and compute basis features."""
    spot_by_ts = {int(r["timestamp"]): float(r["close"]) for r in spot_rows}
    perp_by_ts = {int(r["timestamp"]): float(r["close"]) for r in perp_rows}
    common_ts = sorted(set(spot_by_ts) & set(perp_by_ts))
    if not common_ts:
        return []

    # ``basis_pct`` couvre *tous* les ``common_ts`` (None pour une bougie spot
    # invalide) alors que ``rows_by_ts`` n'en garde que les valides: les series
    # derivees ci-dessous sont donc indexees sur ``common_ts`` et rapatriees par
    # timestamp, jamais par position. L'ancien ``enumerate(rows_raw)`` decalait
    # tous les z-scores d'un cran des qu'une bougie spot <= 0 existait.
    basis_pct: list[float | None] = []
    rows_by_ts: dict[int, dict[str, Any]] = {}
    for ts in common_ts:
        spot = spot_by_ts[ts]
        perp = perp_by_ts[ts]
        if spot <= 0:
            basis_pct.append(None)
            continue
        bp = perp / spot - 1.0
        basis_pct.append(bp)
        rows_by_ts[ts] = {
            "timestamp": ts,
            "spot_price": spot,
            "perp_price": perp,
            "basis_pct": bp,
        }

    z_status = rolling_z_status(basis_pct, z_window)
    compression = _basis_compression_flags(basis_pct, [z for z, _ in z_status])
    out: list[dict[str, Any]] = []
    for ts, (z, status), comp in zip(common_ts, z_status, compression, strict=True):
        row = rows_by_ts.get(ts)
        if row is None:
            continue
        row["basis_zscore"] = z
        row["basis_z_status"] = status
        row["basis_compression"] = comp
        row["basis_extreme"] = z is not None and abs(z) >= extreme_z
        out.append(row)
    return out


_Z_STATUS_VALUES: frozenset[str] = frozenset({"ok", "no_data", "warmup", "flat"})


def _coerce_z_status(raw: Any, z: float | None) -> ZStatus:
    """Statut du z-score, deduit de la valeur pour les caches d'avant Phase 30.

    Un cache ecrit avant l'ajout de ``basis_z_status`` ne peut pas distinguer
    une serie plate: on retombe sur ``ok``/``no_data``, soit exactement le
    comportement anterieur, sans jamais inventer un ``flat``.
    """
    if isinstance(raw, str) and raw in _Z_STATUS_VALUES:
        status: ZStatus = raw  # type: ignore[assignment]
        # Un statut exploitable sans valeur serait incoherent (cache bricole).
        if z is None and status in ("ok", "flat"):
            return "no_data"
        return status
    return "ok" if z is not None else "no_data"


def parse_basis_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in rows:
        ts = raw.get("timestamp")
        if ts is None:
            continue
        try:
            ts_i = int(ts)
            spot = float(raw["spot_price"])
            perp = float(raw["perp_price"])
            bp = float(raw.get("basis_pct", perp / spot - 1.0))
        except (TypeError, ValueError, KeyError):
            continue
        if ts_i in seen or spot <= 0:
            continue
        seen.add(ts_i)
        z_raw = raw.get("basis_zscore")
        z = float(z_raw) if z_raw is not None else None
        comp = bool(raw.get("basis_compression", False))
        extreme = bool(raw.get("basis_extreme", z is not None and abs(z) >= BASIS_EXTREME_Z))
        out.append(
            {
                "timestamp": ts_i,
                "spot_price": spot,
                "perp_price": perp,
                "basis_pct": bp,
                "basis_zscore": z,
                "basis_z_status": _coerce_z_status(raw.get("basis_z_status"), z),
                "basis_compression": comp,
                "basis_extreme": extreme,
            }
        )
    out.sort(key=lambda r: int(r["timestamp"]))
    return out


def load_basis_cache(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = load_json_cache(path)
    if not payload:
        return [], {"status": "blocked_data", "blocked_reason": "cache file missing"}
    entries = payload.get("entries") or {}
    raw = entries.get("rows") if isinstance(entries, dict) else None
    if not isinstance(raw, list):
        raw = payload.get("rows")
    if not isinstance(raw, list):
        return [], {"status": "blocked_data", "blocked_reason": "missing entries.rows"}
    rows = parse_basis_rows(raw)
    meta = {
        "status": "available" if rows else "blocked_data",
        "source": payload.get("source"),
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "row_count": len(rows),
        "fetched_at": payload.get("fetched_at"),
    }
    if not rows:
        meta["blocked_reason"] = "empty rows after parse"
    return rows, meta


def save_basis_cache(
    path: Path,
    *,
    ticker: str,
    timeframe: str,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    parsed = parse_basis_rows(rows)
    sym = futures_symbol(ticker)
    save_json_cache(
        path,
        {
            "source": BASIS_CACHE_SOURCE,
            "kind": "basis",
            "symbol": sym,
            "ticker": ticker.strip().upper().partition("/")[0],
            "timeframe": timeframe.strip().lower(),
            "fetched_at": utc_now_iso(),
            "entries": {"rows": parsed},
        },
    )


def fetch_basis_history(
    ticker: str,
    timeframe: str = "4h",
    *,
    coverage_days: int | None = None,
    fetcher: BinanceFetcherFn = default_http_fetcher,
) -> list[dict[str, Any]]:
    """Fetch spot + mark-price klines and return aligned basis rows."""
    spot = fetch_binance_klines(
        ticker, timeframe, coverage_days=coverage_days, fetcher=fetcher
    )
    perp = fetch_mark_price_klines(
        ticker, timeframe, coverage_days=coverage_days, fetcher=fetcher
    )
    return build_basis_rows(spot, perp)


def audit_basis_readiness(
    tickers: Sequence[str],
    *,
    timeframe: str = "4h",
    cache_dir: Path | None = None,
    min_rows: int = 100,
) -> dict[str, Any]:
    root = cache_dir or DEFAULT_COLLECTOR_CACHE_DIR
    tf = timeframe.strip().lower()
    entries: list[dict[str, Any]] = []
    for ticker in tickers:
        sym = ticker.strip().upper().partition("/")[0]
        path = default_basis_cache_path(sym, tf, root)
        rows, meta = load_basis_cache(path)
        ok = len(rows) >= min_rows
        entries.append(
            {
                "asset": sym,
                "series": f"basis_{tf}",
                "path": str(path),
                "status": "available" if ok else meta.get("status", "blocked_data"),
                "row_count": len(rows),
                "blocked_reason": None if ok else meta.get("blocked_reason"),
            }
        )
    available = sum(1 for e in entries if e.get("status") == "available")
    return {
        "generated_at": utc_now_iso(),
        "cache_root": str(root),
        "timeframe": tf,
        "entries": entries,
        "available_count": available,
        "entries_total": len(entries),
    }
