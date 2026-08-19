#!/usr/bin/env python3
"""Phase 24 data backbone audit — inventory local OHLCV caches (no network)."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.phase24_data_backbone import (  # noqa: E402
    PHASE24_REQUIRED_ASSETS,
    PHASE24_TIMEFRAMES,
    build_inventory,
    summarize_inventory,
)

DEFAULT_CACHE_ROOT = REPO_ROOT / "data" / "collector_cache"
DEFAULT_REPORT_DIR = REPO_ROOT / "reports" / "phase24_data_backbone"


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


def _write_inventory_csv(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not entries:
        return
    fields = sorted({k for e in entries for k in e})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(entries)


def _markdown_report(entries: list[dict], summary: dict) -> str:
    lines = [
        "# Phase 24 — Data backbone audit",
        "",
        f"Generated: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} UTC",
        "",
        "## Summary",
        "",
        f"- Required pairs (BTC/ETH/SOL × 1d/4h): **{summary['required_data_ok']}/{summary['required_pairs']}** data_ok",
        f"- Required complete: **{summary['required_complete']}**",
        f"- Entries audited: **{summary['entries_total']}**",
        f"- data_ok: **{summary['data_ok_count']}**",
        f"- ideal bars (1d≥1000, 4h≥2000): **{summary['ideal_bars_count']}**",
        f"- Longer than Phase 23 `--max-bars {summary['phase23_factory_max_bars']}` cap: "
        f"**{summary['longer_than_phase23_cap']}**",
        "",
        "## Criteria",
        "",
        "- data_ok: 1d ≥500 bars, 4h ≥1000 bars",
        "- ideal: 1d ≥1000, 4h ≥2000",
        f"- Phase 23 factory used last **{summary['phase23_factory_max_bars']}** bars by default",
        "",
        "## Inventory",
        "",
        "| asset | tf | bars | data_ok | ideal | first | last | Δ vs P23 cap |",
        "|-------|-----|------|---------|-------|-------|------|--------------|",
    ]
    for e in sorted(entries, key=lambda x: (x["asset"], x["timeframe"])):
        lines.append(
            f"| {e['asset']} | {e['timeframe']} | {e.get('bar_count', 0)} | "
            f"{e.get('data_ok', False)} | {e.get('ideal_bars', False)} | "
            f"{e.get('first_date_utc', '-')} | {e.get('last_date_utc', '-')} | "
            f"{e.get('delta_bars_vs_phase23_cap', 0)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 24 OHLCV data backbone audit")
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    p.add_argument(
        "--summary-md",
        type=Path,
        default=None,
        help="Chemin du rapport markdown. Par defaut le parent de --report-dir.",
    )
    p.add_argument("--assets", nargs="+", default=list(PHASE24_REQUIRED_ASSETS))
    p.add_argument("--timeframes", nargs="+", default=list(PHASE24_TIMEFRAMES))
    p.add_argument("--no-watchlist", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    entries = build_inventory(
        args.cache_root,
        required_assets=tuple(a.upper() for a in args.assets),
        timeframes=tuple(tf.lower() for tf in args.timeframes),
        include_watchlist=not args.no_watchlist,
    )
    summary = summarize_inventory(entries)
    payload = {
        "phase": 24,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit_sha": _git_commit_sha(),
        "cache_root": str(args.cache_root),
        **summary,
        "entries": entries,
    }

    args.report_dir.mkdir(parents=True, exist_ok=True)
    _write_inventory_csv(args.report_dir / "data_inventory.csv", entries)
    (args.report_dir / "data_quality.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    # Le markdown suit ``--report-dir``. Avec un chemin en dur vers
    # ``reports/PHASE24_DATA_BACKBONE_AUDIT.md``, toute execution hors du
    # repertoire par defaut — a commencer par ``tests/test_data_backbone_audit
    # _phase24.py``, qui seme un cache synthetique BTC/XRP — remplacait le
    # rapport de recherche versionne par sa propre sortie.
    summary_md = args.summary_md or (args.report_dir.parent / "PHASE24_DATA_BACKBONE_AUDIT.md")
    summary_md.parent.mkdir(parents=True, exist_ok=True)
    summary_md.write_text(_markdown_report(entries, summary), encoding="utf-8")
    print(
        json.dumps(
            {"report_dir": str(args.report_dir), "summary_md": str(summary_md), **summary},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
