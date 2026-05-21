#!/usr/bin/env python3
"""Phase 26B — run derivatives event studies (cache-only)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase23_common import DEFAULT_CACHE_ROOT, write_json  # noqa: E402
from src.bot.data_loader import load_ohlcv_candles
from src.bot.derivatives_event_study import (
    classify_event_study_verdict,
    run_all_derivatives_event_studies,
)

DEFAULT_OUT = REPO_ROOT / "reports" / "phase26_event_studies"


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 26 derivatives event study")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH"])
    p.add_argument("--timeframes", nargs="+", default=["4h", "1d"])
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    rows: list[dict] = []
    summaries: list[dict] = []

    for asset in args.assets:
        for tf in args.timeframes:
            candles, summary = load_ohlcv_candles(
                asset, tf, args.cache_root, cache_only=True
            )
            if summary.status != "available":
                summaries.append(
                    {
                        "asset": asset.upper(),
                        "timeframe": tf,
                        "status": "blocked_data",
                        "blocked_reason": summary.blocked_reason,
                    }
                )
                continue
            bundle = run_all_derivatives_event_studies(
                asset, candles, timeframe=tf, cache_root=args.cache_root
            )
            bundle["verdict"] = classify_event_study_verdict(bundle)
            summaries.append(bundle)
            for r in bundle.get("results", []):
                for fs in r.get("forward_stats", []):
                    rows.append(
                        {
                            "asset": bundle["asset"],
                            "timeframe": tf,
                            "signal_id": r["signal_id"],
                            "status": r["status"],
                            "event_count": r["event_count"],
                            **fs,
                        }
                    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "summary.json", {"bundles": summaries})
    if rows:
        fields = sorted({k for r in rows for k in r})
        with (args.output_dir / "results.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    print(json.dumps({"bundles": len(summaries), "csv_rows": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
