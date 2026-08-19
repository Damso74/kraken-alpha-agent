#!/usr/bin/env python3
"""Phase 26A — fetch Binance public funding + OI into gitignored cache."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data.collectors.binance_derivatives_public import (  # noqa: E402
    default_funding_cache_path,
    default_oi_cache_path,
    fetch_funding_rate_history,
    fetch_open_interest_history,
    save_funding_cache,
    save_oi_cache,
)

DEFAULT_CACHE = REPO_ROOT / "data" / "collector_cache"
DEFAULT_ASSETS = ("BTC", "ETH", "SOL")
DEFAULT_FUNDING_DAYS = 730
DEFAULT_OI_DAYS = 30


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Phase 26 derivatives cache (public API)")
    p.add_argument("--assets", nargs="+", default=list(DEFAULT_ASSETS))
    p.add_argument("--funding-days", type=int, default=DEFAULT_FUNDING_DAYS)
    p.add_argument("--oi-days", type=int, default=DEFAULT_OI_DAYS)
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--oi-periods", nargs="+", default=["4h", "1d"])
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    end = datetime.now(UTC)
    end_ms = int(end.timestamp() * 1000)
    funding_start_ms = int((end - timedelta(days=args.funding_days)).timestamp() * 1000)
    oi_start_ms = int((end - timedelta(days=args.oi_days)).timestamp() * 1000)

    for asset in args.assets:
        sym = asset.upper().partition("/")[0]
        fpath = default_funding_cache_path(sym, args.cache_root)
        if args.dry_run:
            print(f"would fetch funding -> {fpath}")
        else:
            rows = fetch_funding_rate_history(
                sym, start_ms=funding_start_ms, end_ms=end_ms
            )
            save_funding_cache(fpath, ticker=sym, rows=rows)
            print(f"funding {sym}: {len(rows)} rows -> {fpath}")

        for period in args.oi_periods:
            opath = default_oi_cache_path(sym, period, args.cache_root)
            if args.dry_run:
                print(f"would fetch oi {period} -> {opath}")
                continue
            rows = fetch_open_interest_history(
                sym, period, start_ms=oi_start_ms, end_ms=end_ms
            )
            save_oi_cache(opath, ticker=sym, period=period, rows=rows)
            print(f"oi {sym} {period}: {len(rows)} rows -> {opath}")

    print("liquidations: blocked_data (no historical public series in Phase 26)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
