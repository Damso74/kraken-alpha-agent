#!/usr/bin/env python3
"""Audit local OHLCV collector caches (no network)."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.data_loader import (  # noqa: E402
    TIMEFRAME_INTERVAL_MINUTES,
    normalize_candle,
    resolve_ohlcv_cache,
    validate_candles,
)
from src.data.collectors.binance_public import (  # noqa: E402
    MIN_ROWS_DATA_OK,
    OHLC_INTRADAY_CACHE_SOURCE,
    load_ohlc_cache_rows,
)

DEFAULT_ASSETS = ("BTC", "ETH", "SOL")
DEFAULT_TIMEFRAMES = ("1d", "4h", "1h")


def _git_commit_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _audit_cache_file(
    asset: str,
    timeframe: str,
    cache_root: Path,
) -> dict[str, Any]:
    resolved = resolve_ohlcv_cache(asset, timeframe, cache_root)
    row: dict[str, Any] = {
        "asset": resolved.asset,
        "timeframe": resolved.timeframe,
        "cache_path": str(resolved.path),
        "row_count": 0,
        "coverage_start": None,
        "coverage_end": None,
        "missing_candles_estimate": 0,
        "duplicate_timestamps": 0,
        "ohlc_invalid_count": 0,
        "volume_missing": 0,
        "timezone": "UTC",
        "sha256": "",
        "source": OHLC_INTRADAY_CACHE_SOURCE,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit_sha": _git_commit_sha(),
        "data_ok": False,
        "blocked_reason": "cache file missing",
    }

    if not resolved.path.is_file():
        return row

    row["sha256"] = hashlib.sha256(resolved.path.read_bytes()).hexdigest()
    try:
        payload = json.loads(resolved.path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("source"):
            row["source"] = str(payload["source"])
        raw_rows = load_ohlc_cache_rows(resolved.path)
    except Exception as exc:  # noqa: BLE001 — audit must not crash
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

    row["row_count"] = len(cleaned)
    row["duplicate_timestamps"] = dup_ts
    row["ohlc_invalid_count"] = invalid
    row["volume_missing"] = vol_missing

    if cleaned:
        row["coverage_start"] = int(cleaned[0]["timestamp"])
        row["coverage_end"] = int(cleaned[-1]["timestamp"])
        span = int(cleaned[-1]["timestamp"]) - int(cleaned[0]["timestamp"])
        step = TIMEFRAME_INTERVAL_MINUTES[resolved.timeframe] * 60
        if span > 0 and step > 0:
            expected = span // step + 1
            row["missing_candles_estimate"] = max(0, expected - len(cleaned))

    min_rows = MIN_ROWS_DATA_OK.get(resolved.timeframe, 30)
    try:
        validate_candles(
            cleaned,
            expected_interval_minutes=resolved.interval_minutes,
        )
        validation_ok = len(cleaned) >= min_rows
    except Exception as exc:  # noqa: BLE001
        validation_ok = False
        row["blocked_reason"] = str(exc)

    if validation_ok:
        row["data_ok"] = True
        row["blocked_reason"] = None
    elif row["blocked_reason"] == "cache file missing":
        row["blocked_reason"] = f"row_count {len(cleaned)} < min {min_rows}"
    elif not row.get("blocked_reason"):
        row["blocked_reason"] = f"row_count {len(cleaned)} < min {min_rows}"

    return row


def audit_manifest(
    *,
    assets: tuple[str, ...] = DEFAULT_ASSETS,
    timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES,
    cache_root: Path,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for asset in assets:
        for tf in timeframes:
            entries.append(_audit_cache_file(asset, tf, cache_root))
    return entries


def can_run_full_tournament(manifest: list[dict[str, Any]]) -> bool:
    """BTC+ETH must have data_ok on 1d, 4h, 1h."""
    required = {("BTC", tf) for tf in ("1d", "4h", "1h")} | {("ETH", tf) for tf in ("1d", "4h", "1h")}
    ok_set = {
        (e["asset"], e["timeframe"])
        for e in manifest
        if e.get("data_ok")
    }
    return required.issubset(ok_set)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit OHLCV caches (local only)")
    p.add_argument("--assets", nargs="+", default=list(DEFAULT_ASSETS))
    p.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    p.add_argument(
        "--cache-root",
        type=Path,
        default=REPO_ROOT / "data" / "collector_cache",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "reports" / "data_manifests_phase21" / "ohlcv_backbone_manifest.json",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    manifest = audit_manifest(
        assets=tuple(a.upper() for a in args.assets),
        timeframes=tuple(tf.lower() for tf in args.timeframes),
        cache_root=args.cache_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit_sha": _git_commit_sha(),
        "can_run_full_tournament": can_run_full_tournament(manifest),
        "entries": manifest,
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "entries": len(manifest), **payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
