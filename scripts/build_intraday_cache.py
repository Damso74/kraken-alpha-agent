#!/usr/bin/env python3
"""Build intraday OHLCV caches from Binance public klines (no API keys)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data.collectors.binance_public import (  # noqa: E402
    TIMEFRAME_COVERAGE_DAYS,
    default_ohlc_cache_path,
    fetch_ohlc_with_cache,
)

DEFAULT_ASSETS = ("BTC", "ETH", "SOL")
DEFAULT_TIMEFRAMES = ("1d", "4h", "1h")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch Binance public OHLCV into data/collector_cache (gitignored)"
    )
    p.add_argument("--assets", nargs="+", default=list(DEFAULT_ASSETS))
    p.add_argument("--timeframes", nargs="+", default=list(DEFAULT_TIMEFRAMES))
    p.add_argument(
        "--cache-root",
        type=Path,
        default=REPO_ROOT / "data" / "collector_cache",
    )
    p.add_argument(
        "--cache-only",
        action="store_true",
        help="Verify existing caches only; no network",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned fetches without network or writes",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    results: list[dict] = []
    exit_code = 0

    for asset in args.assets:
        sym = asset.upper().partition("/")[0]
        for tf in args.timeframes:
            timeframe = tf.lower()
            if timeframe not in TIMEFRAME_COVERAGE_DAYS:
                print(f"skip unsupported timeframe: {tf}", file=sys.stderr)
                continue
            cache_path = default_ohlc_cache_path(sym, timeframe)
            if args.cache_root != cache_path.parent:
                cache_path = args.cache_root / cache_path.name

            if args.dry_run:
                results.append(
                    {
                        "asset": sym,
                        "timeframe": timeframe,
                        "cache_path": str(cache_path),
                        "coverage_days": TIMEFRAME_COVERAGE_DAYS[timeframe],
                        "status": "dry_run",
                    }
                )
                continue

            try:
                rows = fetch_ohlc_with_cache(
                    sym,
                    timeframe,
                    cache_path=cache_path,
                    use_cache_only=args.cache_only,
                )
                results.append(
                    {
                        "asset": sym,
                        "timeframe": timeframe,
                        "cache_path": str(cache_path),
                        "row_count": len(rows),
                        "coverage_start": int(rows[0]["timestamp"]) if rows else None,
                        "coverage_end": int(rows[-1]["timestamp"]) if rows else None,
                        "status": "ok",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                exit_code = 1
                results.append(
                    {
                        "asset": sym,
                        "timeframe": timeframe,
                        "cache_path": str(cache_path),
                        "status": "error",
                        "error": str(exc),
                    }
                )

    print(json.dumps({"results": results}, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
