"""Phase 24 OHLCV data backbone audit (cache-only, no network)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.bot.data_loader import (
    TIMEFRAME_INTERVAL_MINUTES,
    normalize_candle,
    resolve_ohlcv_cache,
    validate_candles,
)

PHASE24_REQUIRED_ASSETS = ("BTC", "ETH", "SOL")
PHASE24_TIMEFRAMES = ("1d", "4h")
PHASE24_MIN_BARS: dict[str, int] = {"1d": 500, "4h": 1000}
PHASE24_IDEAL_BARS: dict[str, int] = {"1d": 1000, "4h": 2000}
PHASE23_FACTORY_MAX_BARS = 500

_OHLC_CACHE_RE = re.compile(r"^ohlc_(?:daily|4h|1h)_([A-Z0-9]+)\.json$", re.IGNORECASE)


def discover_cached_assets(cache_root: Path) -> list[str]:
    """Assets with at least one OHLC cache file under cache_root."""
    found: set[str] = set()
    if not cache_root.is_dir():
        return []
    for path in cache_root.iterdir():
        if not path.is_file():
            continue
        m = _OHLC_CACHE_RE.match(path.name)
        if m:
            found.add(m.group(1).upper())
    return sorted(found)


def audit_cache_entry(
    asset: str,
    timeframe: str,
    cache_root: Path,
) -> dict[str, Any]:
    """Audit one asset/timeframe cache file."""
    resolved = resolve_ohlcv_cache(asset, timeframe, cache_root)
    row: dict[str, Any] = {
        "asset": resolved.asset,
        "timeframe": resolved.timeframe,
        "cache_path": str(resolved.path),
        "bar_count": 0,
        "first_date_utc": None,
        "last_date_utc": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "coverage_days": 0.0,
        "missing_candles_estimate": 0,
        "duplicate_timestamps": 0,
        "ohlc_invalid_count": 0,
        "volume_missing": 0,
        "gaps_detected": 0,
        "sha256": "",
        "data_ok": False,
        "ideal_bars": False,
        "blocked_reason": "cache file missing",
        "phase23_capped_bars": min(PHASE23_FACTORY_MAX_BARS, 0),
        "delta_bars_vs_phase23_cap": 0,
    }

    if not resolved.path.is_file():
        return row

    row["sha256"] = hashlib.sha256(resolved.path.read_bytes()).hexdigest()
    try:
        import json

        payload = json.loads(resolved.path.read_text(encoding="utf-8"))
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if isinstance(entries, dict) and isinstance(entries.get("candles"), list):
            raw_rows = entries["candles"]
        elif isinstance(payload, dict) and isinstance(payload.get("candles"), list):
            raw_rows = payload["candles"]
        else:
            from src.data.collectors.binance_public import load_ohlc_cache_rows

            raw_rows = load_ohlc_cache_rows(resolved.path)
    except Exception as exc:  # noqa: BLE001
        row["blocked_reason"] = str(exc)
        return row

    dup_ts = 0
    invalid = 0
    vol_missing = 0
    seen: set[int] = set()
    cleaned: list[dict[str, Any]] = []
    for raw in raw_rows:
        if raw.get("volume") is None:
            vol_missing += 1
        norm = normalize_candle(raw)
        if norm is None:
            invalid += 1
            continue
        ts = int(norm["timestamp"])
        if ts in seen:
            dup_ts += 1
            continue
        seen.add(ts)
        cleaned.append(norm)

    row["bar_count"] = len(cleaned)
    row["duplicate_timestamps"] = dup_ts
    row["ohlc_invalid_count"] = invalid
    row["volume_missing"] = vol_missing
    row["phase23_capped_bars"] = min(PHASE23_FACTORY_MAX_BARS, len(cleaned))
    row["delta_bars_vs_phase23_cap"] = max(0, len(cleaned) - PHASE23_FACTORY_MAX_BARS)

    if cleaned:
        first_ts = int(cleaned[0]["timestamp"])
        last_ts = int(cleaned[-1]["timestamp"])
        row["first_timestamp"] = first_ts
        row["last_timestamp"] = last_ts
        row["first_date_utc"] = datetime.fromtimestamp(
            first_ts, tz=UTC
        ).strftime("%Y-%m-%d")
        row["last_date_utc"] = datetime.fromtimestamp(
            last_ts, tz=UTC
        ).strftime("%Y-%m-%d")
        span = last_ts - first_ts
        row["coverage_days"] = round(span / 86400.0, 2)
        step = TIMEFRAME_INTERVAL_MINUTES[resolved.timeframe] * 60
        if span > 0 and step > 0:
            expected = span // step + 1
            row["missing_candles_estimate"] = max(0, expected - len(cleaned))
            row["gaps_detected"] = row["missing_candles_estimate"]

    min_bars = PHASE24_MIN_BARS.get(resolved.timeframe, 30)
    ideal_bars = PHASE24_IDEAL_BARS.get(resolved.timeframe, min_bars)
    try:
        validate_candles(
            cleaned,
            expected_interval_minutes=resolved.interval_minutes,
        )
        validation_ok = len(cleaned) >= min_bars
    except Exception as exc:  # noqa: BLE001
        validation_ok = False
        row["blocked_reason"] = str(exc)

    if validation_ok:
        row["data_ok"] = True
        row["ideal_bars"] = len(cleaned) >= ideal_bars
        row["blocked_reason"] = None
    elif row["blocked_reason"] == "cache file missing":
        row["blocked_reason"] = f"bar_count {len(cleaned)} < min {min_bars}"
    elif not row.get("blocked_reason"):
        row["blocked_reason"] = f"bar_count {len(cleaned)} < min {min_bars}"

    return row


def build_inventory(
    cache_root: Path,
    *,
    required_assets: tuple[str, ...] = PHASE24_REQUIRED_ASSETS,
    timeframes: tuple[str, ...] = PHASE24_TIMEFRAMES,
    include_watchlist: bool = True,
) -> list[dict[str, Any]]:
    """Audit required assets plus any extra assets already present in cache."""
    assets = list(required_assets)
    if include_watchlist:
        for sym in discover_cached_assets(cache_root):
            if sym not in assets:
                assets.append(sym)
    entries: list[dict[str, Any]] = []
    for asset in assets:
        for tf in timeframes:
            entries.append(audit_cache_entry(asset, tf, cache_root))
    return entries


def summarize_inventory(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts for reports and JSON manifest."""
    required = {(a, tf) for a in PHASE24_REQUIRED_ASSETS for tf in PHASE24_TIMEFRAMES}
    ok_required = {
        (e["asset"], e["timeframe"])
        for e in entries
        if e.get("data_ok") and (e["asset"], e["timeframe"]) in required
    }
    longer_than_phase23 = [
        e
        for e in entries
        if e.get("data_ok") and int(e.get("delta_bars_vs_phase23_cap", 0)) > 0
    ]
    return {
        "required_pairs": len(required),
        "required_data_ok": len(ok_required),
        "required_complete": ok_required == required,
        "entries_total": len(entries),
        "data_ok_count": sum(1 for e in entries if e.get("data_ok")),
        "ideal_bars_count": sum(1 for e in entries if e.get("ideal_bars")),
        "longer_than_phase23_cap": len(longer_than_phase23),
        "phase23_factory_max_bars": PHASE23_FACTORY_MAX_BARS,
    }
