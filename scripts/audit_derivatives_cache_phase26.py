#!/usr/bin/env python3
"""Phase 26A — audit derivatives cache readiness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data.collectors.binance_derivatives_public import audit_derivatives_readiness  # noqa: E402

DEFAULT_CACHE = REPO_ROOT / "data" / "collector_cache"
DEFAULT_OUT = REPO_ROOT / "reports" / "data_manifests_phase26" / "derivatives_readiness.json"


def main() -> int:
    p = argparse.ArgumentParser(description="Audit Phase 26 derivatives caches")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL"])
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    manifest = audit_derivatives_readiness(args.assets, cache_dir=args.cache_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0 if manifest.get("available_count", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
