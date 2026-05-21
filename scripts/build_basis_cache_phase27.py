#!/usr/bin/env python3
"""Phase 27A — fetch Binance spot/perp basis into gitignored cache."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data.collectors.binance_basis_public import (  # noqa: E402
    audit_basis_readiness,
    default_basis_cache_path,
    fetch_basis_history,
    save_basis_cache,
)

DEFAULT_CACHE = REPO_ROOT / "data" / "collector_cache"
DEFAULT_ASSETS = ("BTC", "ETH")
DEFAULT_TIMEFRAME = "4h"
DEFAULT_OUT = REPO_ROOT / "reports" / "data_manifests_phase27" / "basis_readiness.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Phase 27 basis cache (public API)")
    p.add_argument("--assets", nargs="+", default=list(DEFAULT_ASSETS))
    p.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--manifest", type=Path, default=DEFAULT_OUT)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    for asset in args.assets:
        sym = asset.upper().partition("/")[0]
        path = default_basis_cache_path(sym, args.timeframe, args.cache_root)
        if args.dry_run:
            print(f"would fetch basis {sym} {args.timeframe} -> {path}")
            continue
        rows = fetch_basis_history(sym, args.timeframe)
        save_basis_cache(path, ticker=sym, timeframe=args.timeframe, rows=rows)
        print(f"basis {sym} {args.timeframe}: {len(rows)} rows -> {path}")

    if not args.dry_run:
        manifest = audit_basis_readiness(
            args.assets, timeframe=args.timeframe, cache_dir=args.cache_root
        )
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            __import__("json").dumps(manifest, indent=2), encoding="utf-8"
        )
        print(f"manifest -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
