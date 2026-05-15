"""Synthesise a paper / dry-run session into a Markdown + JSON report.

Reads from SQLite (`cycles`, `decisions`, `orders`, `pnl_snapshots`,
`errors`) and the JSONL mirrors under `data/`. Writes:

- ``data/paper_run_report_<ts>.md``   human-readable summary
- ``data/paper_run_report_<ts>.json`` machine-readable payload
- ``data/paper_run_report_latest.md`` / ``.json`` (overwritten, used by the
  dashboard when a stable filename is more convenient)

The script is safe to run at any time — if no data is available the report
declares so and exits with status 0.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import storage
from src.config import get_settings
from src.logger import get_logger
from src.paper_run_analysis import compute_report, render_markdown
from src.utils import utc_now_iso

logger = get_logger("analyze_paper_run")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyse a paper / dry-run session.")
    p.add_argument("--since", type=float, default=24.0, help="window in hours (default 24)")
    p.add_argument("--out", type=str, default=None, help="explicit Markdown output path")
    p.add_argument("--output-dir", type=str, default="data", help="output directory")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    settings = get_settings()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[analyze] {utc_now_iso()} reading audit tables...")
    try:
        decisions = storage.fetch_recent_decisions(limit=2000)
    except Exception as exc:  # noqa: BLE001
        logger.warning("decisions fetch failed: %s", exc)
        decisions = []
    try:
        orders = storage.fetch_recent_orders(limit=2000)
    except Exception as exc:  # noqa: BLE001
        logger.warning("orders fetch failed: %s", exc)
        orders = []
    try:
        pnl_snaps = storage.fetch_recent_pnl(limit=500)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pnl fetch failed: %s", exc)
        pnl_snaps = []
    try:
        cycles = storage.fetch_recent_cycles(limit=2000)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cycles fetch failed: %s", exc)
        cycles = []
    try:
        errors = storage.fetch_recent_errors(limit=500)
    except Exception as exc:  # noqa: BLE001
        logger.warning("errors fetch failed: %s", exc)
        errors = []

    report = compute_report(
        decisions=decisions,
        orders=orders,
        pnl_snapshots=pnl_snaps,
        cycles=cycles,
        errors=errors,
        since_hours=float(args.since),
        profile=settings.active_profile,
        generated_at=utc_now_iso(),
    )

    md = render_markdown(report)
    payload = report.to_dict()

    ts = time.strftime("%Y%m%dT%H%M%S")
    md_path = Path(args.out) if args.out else out_dir / f"paper_run_report_{ts}.md"
    json_path = md_path.with_suffix(".json")
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    # Stable "latest" copy for the dashboard / share links.
    (out_dir / "paper_run_report_latest.md").write_text(md, encoding="utf-8")
    (out_dir / "paper_run_report_latest.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )

    if report.no_data:
        print("[analyze] No data in the requested window — report still written.")
    else:
        print(
            f"[analyze] {report.decisions_count} decisions, {len(report.fifo_trades)} "
            f"FIFO trades, net PnL ${report.pnl_net_usd:,.2f}"
        )
    print(f"[analyze] markdown : {md_path}")
    print(f"[analyze] json     : {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
