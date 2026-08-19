"""OHLCV cache loader for paper-bot tournaments (cache-only, no network)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.data.collectors._common import DEFAULT_COLLECTOR_CACHE_DIR
from src.data.collectors.binance_public import parse_ohlc_candle_rows

REQUIRED_COLUMNS = frozenset({"timestamp", "open", "high", "low", "close", "volume"})

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


@dataclass(frozen=True)
class CacheResolveResult:
    asset: str
    timeframe: str
    path: Path
    exists: bool
    interval_minutes: int


@dataclass(frozen=True)
class CandleSummary:
    asset: str
    timeframe: str
    path: str
    candle_count: int
    usable_bars: int
    warmup_bars: int
    first_timestamp: int | None
    last_timestamp: int | None
    coverage_days: float
    sha256: str
    interval_minutes: int
    columns_ok: bool
    status: str
    blocked_reason: str | None = None


class DataLoaderError(Exception):
    """Raised when cache is missing or candles fail validation."""


def resolve_ohlcv_cache(
    asset: str,
    timeframe: str,
    cache_root: Path | str | None = None,
) -> CacheResolveResult:
    """Resolve cache path for asset/timeframe without loading."""
    tf = timeframe.strip().lower()
    if tf not in TIMEFRAME_INTERVAL_MINUTES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    sym = asset.strip().upper().partition("/")[0]
    root = Path(cache_root) if cache_root is not None else DEFAULT_COLLECTOR_CACHE_DIR
    basename = TIMEFRAME_CACHE_BASENAME[tf]
    path = root / f"{basename}_{sym}.json"
    return CacheResolveResult(
        asset=sym,
        timeframe=tf,
        path=path,
        exists=path.is_file(),
        interval_minutes=TIMEFRAME_INTERVAL_MINUTES[tf],
    )


def normalize_candle(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize a single OHLCV row; return None if invalid."""
    ts = raw.get("timestamp")
    if not isinstance(ts, int):
        return None
    try:
        o = float(raw["open"])
        h = float(raw["high"])
        lo = float(raw["low"])
        c = float(raw["close"])
        vol = float(raw.get("volume", 0.0))
    except (KeyError, TypeError, ValueError):
        return None
    if o <= 0 or h <= 0 or lo <= 0 or c <= 0 or vol < 0:
        return None
    if h < max(o, c, lo) - 1e-12 or lo > min(o, c, h) + 1e-12:
        return None
    vwap_raw = raw.get("vwap")
    if vwap_raw is not None:
        try:
            vwap = float(vwap_raw)
        except (TypeError, ValueError):
            vwap = (h + lo + c) / 3.0
    else:
        vwap = (h + lo + c) / 3.0
    return {
        "timestamp": ts,
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "vwap": vwap,
        "volume": vol,
    }


def validate_candles(
    candles: Sequence[Mapping[str, Any]],
    *,
    expected_interval_minutes: int | None = None,
) -> list[dict[str, Any]]:
    """Parse, validate monotonic unique timestamps, reject invalid OHLC."""
    out: list[dict[str, Any]] = []
    seen_ts: set[int] = set()
    prev_ts: int | None = None
    for raw in candles:
        row = normalize_candle(raw)
        if row is None:
            raise DataLoaderError("invalid OHLCV row (bad prices or types)")
        ts = int(row["timestamp"])
        if ts in seen_ts:
            raise DataLoaderError(f"duplicate timestamp: {ts}")
        if prev_ts is not None and ts <= prev_ts:
            raise DataLoaderError(f"non-monotonic timestamp: {ts} <= {prev_ts}")
        seen_ts.add(ts)
        prev_ts = ts
        out.append(row)
    if expected_interval_minutes is not None and out:
        _check_interval_spacing(out, expected_interval_minutes)
    return out


def _check_interval_spacing(rows: list[dict[str, Any]], interval_minutes: int) -> None:
    """Warn-level spacing check: large gaps allowed (weekends); reject backward steps only."""
    step = interval_minutes * 60
    for i in range(1, min(len(rows), 50)):
        delta = int(rows[i]["timestamp"]) - int(rows[i - 1]["timestamp"])
        if delta <= 0:
            raise DataLoaderError("non-monotonic timestamps in sample")


def _read_cache_payload(path: Path) -> tuple[list[Any], int | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DataLoaderError(f"cache root is not an object: {path}")
    entries = payload.get("entries")
    if isinstance(entries, dict) and isinstance(entries.get("candles"), list):
        raw = entries["candles"]
    elif isinstance(payload.get("candles"), list):
        raw = payload["candles"]
    else:
        raise DataLoaderError(f"missing entries.candles in {path}")
    interval = payload.get("interval_minutes")
    if interval is not None:
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            interval = None
    return raw, interval


def load_ohlcv_candles(
    asset: str,
    timeframe: str,
    cache_root: Path | str | None = None,
    *,
    cache_only: bool = True,
    warmup_bars: int = 0,
) -> tuple[list[dict[str, Any]], CandleSummary]:
    """Load candles from local cache; missing cache → blocked summary, empty list."""
    _ = cache_only  # explicit contract — never fetch network from this module
    resolved = resolve_ohlcv_cache(asset, timeframe, cache_root)
    if not resolved.exists:
        summary = CandleSummary(
            asset=resolved.asset,
            timeframe=resolved.timeframe,
            path=str(resolved.path),
            candle_count=0,
            usable_bars=0,
            warmup_bars=warmup_bars,
            first_timestamp=None,
            last_timestamp=None,
            coverage_days=0.0,
            sha256="",
            interval_minutes=resolved.interval_minutes,
            columns_ok=False,
            status="blocked_data",
            blocked_reason="cache file missing",
        )
        return [], summary

    raw_rows, file_interval = _read_cache_payload(resolved.path)
    if file_interval is not None and file_interval != resolved.interval_minutes:
        raise DataLoaderError(
            f"interval mismatch in {resolved.path}: file={file_interval} expected={resolved.interval_minutes}"
        )

    candles = validate_candles(raw_rows, expected_interval_minutes=resolved.interval_minutes)
    sha = hashlib.sha256(resolved.path.read_bytes()).hexdigest()
    first_ts = int(candles[0]["timestamp"]) if candles else None
    last_ts = int(candles[-1]["timestamp"]) if candles else None
    coverage = 0.0
    if first_ts is not None and last_ts is not None and last_ts > first_ts:
        coverage = (last_ts - first_ts) / 86400.0

    usable = max(0, len(candles) - warmup_bars)
    summary = CandleSummary(
        asset=resolved.asset,
        timeframe=resolved.timeframe,
        path=str(resolved.path),
        candle_count=len(candles),
        usable_bars=usable,
        warmup_bars=warmup_bars,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        coverage_days=round(coverage, 2),
        sha256=sha,
        interval_minutes=resolved.interval_minutes,
        columns_ok=True,
        status="available",
    )
    return candles, summary


def summarize_candles(
    asset: str,
    timeframe: str,
    cache_root: Path | str | None = None,
    *,
    warmup_bars: int = 0,
) -> CandleSummary:
    """Summarize cache without full validation pass (audit manifest)."""
    resolved = resolve_ohlcv_cache(asset, timeframe, cache_root)
    if not resolved.exists:
        return CandleSummary(
            asset=resolved.asset,
            timeframe=resolved.timeframe,
            path=str(resolved.path),
            candle_count=0,
            usable_bars=0,
            warmup_bars=warmup_bars,
            first_timestamp=None,
            last_timestamp=None,
            coverage_days=0.0,
            sha256="",
            interval_minutes=resolved.interval_minutes,
            columns_ok=False,
            status="blocked_data",
            blocked_reason="cache file missing",
        )
    try:
        raw_rows, file_interval = _read_cache_payload(resolved.path)
        normalize_daily = file_interval is None or int(file_interval) >= 1440
        parsed = parse_ohlc_candle_rows(raw_rows, normalize_to_day=normalize_daily)
    except Exception as exc:  # noqa: BLE001 — audit path
        return CandleSummary(
            asset=resolved.asset,
            timeframe=resolved.timeframe,
            path=str(resolved.path),
            candle_count=0,
            usable_bars=0,
            warmup_bars=warmup_bars,
            first_timestamp=None,
            last_timestamp=None,
            coverage_days=0.0,
            sha256=hashlib.sha256(resolved.path.read_bytes()).hexdigest(),
            interval_minutes=resolved.interval_minutes,
            columns_ok=False,
            status="blocked_data",
            blocked_reason=str(exc),
        )
    sha = hashlib.sha256(resolved.path.read_bytes()).hexdigest()
    first_ts = int(parsed[0]["timestamp"]) if parsed else None
    last_ts = int(parsed[-1]["timestamp"]) if parsed else None
    coverage = 0.0
    if first_ts is not None and last_ts is not None and last_ts > first_ts:
        coverage = (last_ts - first_ts) / 86400.0
    usable = max(0, len(parsed) - warmup_bars)
    return CandleSummary(
        asset=resolved.asset,
        timeframe=resolved.timeframe,
        path=str(resolved.path),
        candle_count=len(parsed),
        usable_bars=usable,
        warmup_bars=warmup_bars,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        coverage_days=round(coverage, 2),
        sha256=sha,
        interval_minutes=resolved.interval_minutes,
        columns_ok=bool(parsed),
        status="available" if parsed else "blocked_data",
    )
