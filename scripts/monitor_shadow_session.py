"""Read-only realtime monitor for the xStocks dry-run shadow session.

This monitor never writes anything to ``data/agent.sqlite`` (opens the
SQLite database with ``mode=ro&immutable=0``) and never modifies any
file under ``data/``. It is safe to run alongside the live launcher in
``scripts/launch_shadow_xstocks.ps1``.

What it shows (refreshed every ``--refresh-seconds``, default 30s):

* Session start (UTC) + uptime + remaining time before the
  ``--cutoff`` deadline (defaults to May 20 12:00 CEST = the lablab
  submission window's end).
* Cycle counters since session start: total, mode-breakdown,
  approved decisions.
* Simulated trades since session start: count, win rate, cumulative
  fees and net PnL.
* Open simulated positions (read from ``positions`` table).
* Last error (if any) recorded in the ``errors`` table.

Inputs:

* ``data/shadow_session.json`` — written by the launcher with
  ``started_at_utc`` and metadata. The monitor uses ``--since`` to
  override or ``--auto`` (default) to look for the metadata file.

Usage::

    .\\.venv\\Scripts\\Activate.ps1
    python scripts/monitor_shadow_session.py
    # or with explicit start time:
    python scripts/monitor_shadow_session.py --since 2026-05-18T19:00:00Z
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB = ROOT / "data" / "agent.sqlite"
DEFAULT_METADATA = ROOT / "data" / "shadow_session.json"
DEFAULT_LOG = ROOT / "data" / "shadow_session.log"

# Lablab Hackathon submission cut-off: Wed 20 May 2026 12:00 CEST
DEFAULT_CUTOFF_ISO = "2026-05-20T10:00:00Z"  # 12:00 CEST = 10:00 UTC


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read-only realtime monitor for the xStocks dry-run shadow "
            "session. NEVER writes to data/."
        )
    )
    p.add_argument(
        "--refresh-seconds",
        type=float,
        default=30.0,
        help="UI refresh interval in seconds (default 30s).",
    )
    p.add_argument(
        "--db",
        type=str,
        default=str(DEFAULT_DB),
        help="path to data/agent.sqlite (default uses repo path).",
    )
    p.add_argument(
        "--metadata",
        type=str,
        default=str(DEFAULT_METADATA),
        help=(
            "path to data/shadow_session.json written by the launcher. "
            "Used to discover the session start time."
        ),
    )
    p.add_argument(
        "--since",
        type=str,
        default=None,
        help=(
            "explicit session start UTC ISO-8601 (e.g. 2026-05-18T19:00:00Z). "
            "Overrides --metadata when set."
        ),
    )
    p.add_argument(
        "--cutoff",
        type=str,
        default=DEFAULT_CUTOFF_ISO,
        help=(
            "session end target as UTC ISO-8601 (default May 20 10:00 UTC = "
            "12:00 CEST, the lablab submission deadline)."
        ),
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="render a single snapshot and exit (smoke check / CI).",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    started_at_utc: datetime
    cutoff_at_utc: datetime
    db_path: Path
    log_path: Path
    metadata: dict[str, Any]


def _parse_iso(ts: str) -> datetime:
    s = ts.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load_metadata(metadata_path: Path) -> dict[str, Any]:
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _resolve_started_at(args: argparse.Namespace) -> tuple[datetime, dict[str, Any]]:
    metadata: dict[str, Any] = _load_metadata(Path(args.metadata))
    if args.since:
        return _parse_iso(args.since), metadata
    if metadata.get("started_at_utc"):
        return _parse_iso(metadata["started_at_utc"]), metadata
    # Fallback: assume the session started just now (best-effort, the
    # operator can pass --since to be precise).
    return _now_utc(), metadata


# ---------------------------------------------------------------------------
# SQLite read-only queries
# ---------------------------------------------------------------------------


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """Open the SQLite DB read-only via URI mode. The launcher uses WAL
    journaling so we get a consistent snapshot even when the writer is
    appending in parallel.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"agent SQLite DB not found at {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _query_metrics(state: SessionState) -> dict[str, Any]:
    """Aggregate metrics from data/agent.sqlite since session start.

    All queries filter on ``at >= state.started_at_utc`` so the monitor
    counts only events from the current session, ignoring older runs
    that share the same DB.
    """
    started_iso = _fmt_iso(state.started_at_utc)
    metrics: dict[str, Any] = {
        "started_at": started_iso,
        "cycles_total": 0,
        "cycles_by_mode": [],
        "decisions_total": 0,
        "decisions_approved": 0,
        "trades_total": 0,
        "trades_dry_run": 0,
        "trades_filled_status_breakdown": [],
        "fees_usd": 0.0,
        "realised_pnl_usd": 0.0,
        "open_positions": [],
        "last_error": None,
        "last_pnl_snapshot": None,
        "universe_seen": [],
    }

    try:
        conn = _connect_ro(state.db_path)
    except FileNotFoundError as exc:
        metrics["error"] = str(exc)
        return metrics

    try:
        # Cycles
        rows = conn.execute(
            "SELECT mode, COUNT(*) AS n FROM cycles WHERE started_at >= ? GROUP BY mode",
            (started_iso,),
        ).fetchall()
        metrics["cycles_by_mode"] = [{"mode": r["mode"], "count": r["n"]} for r in rows]
        metrics["cycles_total"] = sum(r["n"] for r in rows)

        # Decisions
        d_row = conn.execute(
            "SELECT COUNT(*) AS n, SUM(CASE WHEN approved=1 THEN 1 ELSE 0 END) AS approved "
            "FROM decisions WHERE at >= ?",
            (started_iso,),
        ).fetchone()
        if d_row is not None:
            metrics["decisions_total"] = int(d_row["n"] or 0)
            metrics["decisions_approved"] = int(d_row["approved"] or 0)

        # Orders / trades
        trade_rows = conn.execute(
            "SELECT status, mode, COUNT(*) AS n, "
            "       SUM(COALESCE(fee, 0.0)) AS fee_sum, "
            "       SUM(COALESCE(filled_size_usd, 0.0)) AS filled_sum "
            "FROM orders WHERE at >= ? GROUP BY status, mode",
            (started_iso,),
        ).fetchall()
        metrics["trades_filled_status_breakdown"] = [
            {
                "status": r["status"],
                "mode": r["mode"],
                "count": int(r["n"]),
                "fee_sum_usd": float(r["fee_sum"] or 0.0),
                "filled_sum_usd": float(r["filled_sum"] or 0.0),
            }
            for r in trade_rows
        ]
        metrics["trades_total"] = sum(b["count"] for b in metrics["trades_filled_status_breakdown"])
        metrics["trades_dry_run"] = sum(
            b["count"]
            for b in metrics["trades_filled_status_breakdown"]
            if b["mode"] == "dry_run" and b["status"] == "dry_run_logged"
        )
        metrics["fees_usd"] = sum(
            float(b["fee_sum_usd"] or 0.0)
            for b in metrics["trades_filled_status_breakdown"]
        )

        # Open positions snapshot (most recent persisted state)
        pos_rows = conn.execute(
            "SELECT symbol, quantity, avg_entry_price, market_price, notional_usd, "
            "       unrealized_pnl_usd, realized_pnl_usd, opened_at "
            "FROM positions ORDER BY symbol"
        ).fetchall()
        metrics["open_positions"] = [
            {
                "symbol": r["symbol"],
                "qty": float(r["quantity"]),
                "avg_entry": float(r["avg_entry_price"]),
                "mark": float(r["market_price"]),
                "notional_usd": float(r["notional_usd"]),
                "unrealized_pnl_usd": float(r["unrealized_pnl_usd"]),
                "realized_pnl_usd": float(r["realized_pnl_usd"]),
                "opened_at": r["opened_at"],
            }
            for r in pos_rows
            if abs(float(r["quantity"])) > 1e-9
        ]

        # Realised PnL since start (sum of realized_pnl_usd from positions
        # that were closed during this session is hard to recover from the
        # positions table alone; we take the latest pnl_snapshot as a
        # better proxy).
        pnl_row = conn.execute(
            "SELECT realized_usd, unrealized_usd, net_usd, equity_usd, drawdown_pct, at "
            "FROM pnl_snapshots WHERE at >= ? ORDER BY at DESC LIMIT 1",
            (started_iso,),
        ).fetchone()
        if pnl_row is not None:
            metrics["last_pnl_snapshot"] = {
                "at": pnl_row["at"],
                "realized_usd": float(pnl_row["realized_usd"]),
                "unrealized_usd": float(pnl_row["unrealized_usd"]),
                "net_usd": float(pnl_row["net_usd"]),
                "equity_usd": float(pnl_row["equity_usd"]),
                "drawdown_pct": float(pnl_row["drawdown_pct"]),
            }

        # Latest error (if any) since session start
        err_row = conn.execute(
            "SELECT at, where_label, message FROM errors WHERE at >= ? "
            "ORDER BY at DESC LIMIT 1",
            (started_iso,),
        ).fetchone()
        if err_row is not None:
            metrics["last_error"] = {
                "at": err_row["at"],
                "where": err_row["where_label"],
                "message": err_row["message"],
            }

        # Universe seen during the session (from cycles.summary_json)
        seen: set[str] = set()
        for row in conn.execute(
            "SELECT summary_json FROM cycles WHERE started_at >= ? LIMIT 200",
            (started_iso,),
        ).fetchall():
            blob = row["summary_json"] or "{}"
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            for s in data.get("approved_actions") or []:
                seen.add(s)
        # Fallback: scan recent decisions for the symbol set.
        if not seen:
            for row in conn.execute(
                "SELECT DISTINCT symbol FROM decisions WHERE at >= ?",
                (started_iso,),
            ).fetchall():
                if row["symbol"]:
                    seen.add(row["symbol"])
        metrics["universe_seen"] = sorted(seen)

    finally:
        conn.close()

    return metrics


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_duration(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total <= 0:
        return "(elapsed)"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _fmt_money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.4f}"


def _render(state: SessionState) -> str:
    metrics = _query_metrics(state)
    now = _now_utc()
    elapsed = now - state.started_at_utc
    remaining = state.cutoff_at_utc - now

    parts: list[str] = []
    parts.append("=" * 72)
    parts.append("KRAKEN ALPHA AGENT — SHADOW XSTOCKS DRY-RUN MONITOR (read-only)")
    parts.append("=" * 72)
    parts.append(
        "  MONITORING — NE PAS FERMER TANT QUE TU NE VEUX PAS ARRÊTER LA SESSION."
    )
    parts.append(
        "  Cette fenêtre est read-only. Pour stopper la session, va dans la "
        "fenêtre du launcher (scripts/launch_shadow_xstocks.ps1) et fais Ctrl+C."
    )
    parts.append("")
    parts.append(
        f"  started_at (UTC) : {_fmt_iso(state.started_at_utc)}"
        f"   uptime: {_fmt_duration(elapsed)}"
    )
    parts.append(
        f"  cutoff_at  (UTC) : {_fmt_iso(state.cutoff_at_utc)}"
        f"   remaining: {_fmt_duration(remaining)}"
    )
    if state.metadata:
        parts.append(
            f"  profile          : {state.metadata.get('profile', 'unknown')}"
            f"   loop_interval_s: {state.metadata.get('loop_interval_s', '?')}"
            f"   pid: {state.metadata.get('pid', '?')}"
        )
        parts.append(f"  log_file         : {state.metadata.get('log_file', '?')}")

    if "error" in metrics:
        parts.append("")
        parts.append(f"  WARN: {metrics['error']}")
        return "\n".join(parts)

    # Cycles
    parts.append("")
    parts.append("--- Cycles since session start ---")
    parts.append(
        f"  total: {metrics['cycles_total']}  "
        f"by_mode: {metrics['cycles_by_mode'] or '(none yet)'}"
    )
    if metrics["universe_seen"]:
        parts.append(f"  universe seen: {metrics['universe_seen']}")

    # Decisions
    parts.append("")
    parts.append("--- Decisions ---")
    parts.append(
        f"  total: {metrics['decisions_total']}  "
        f"approved: {metrics['decisions_approved']}"
    )

    # Orders / simulated trades
    parts.append("")
    parts.append("--- Simulated orders (dry_run_logged = bot acted on a signal) ---")
    parts.append(
        f"  trades_total: {metrics['trades_total']}  "
        f"trades_dry_run: {metrics['trades_dry_run']}  "
        f"fees_usd: {_fmt_money(metrics['fees_usd'])}"
    )
    if metrics["trades_filled_status_breakdown"]:
        for b in metrics["trades_filled_status_breakdown"]:
            parts.append(
                f"   - status={b['status']:<28} mode={b['mode']:<8} "
                f"count={b['count']:<6} fee_sum={_fmt_money(b['fee_sum_usd'])}"
                f"  filled_sum={_fmt_money(b['filled_sum_usd'])}"
            )

    # PnL snapshot
    pnl = metrics.get("last_pnl_snapshot")
    parts.append("")
    parts.append("--- Latest PnL snapshot ---")
    if pnl is None:
        parts.append("  (no pnl snapshot since session start)")
    else:
        parts.append(
            f"  at={pnl['at']}  realized={_fmt_money(pnl['realized_usd'])}  "
            f"unrealized={_fmt_money(pnl['unrealized_usd'])}  "
            f"net={_fmt_money(pnl['net_usd'])}  equity={_fmt_money(pnl['equity_usd'])}"
            f"  drawdown={pnl['drawdown_pct']:.2f}%"
        )

    # Open positions
    parts.append("")
    parts.append("--- Open simulated positions ---")
    if not metrics["open_positions"]:
        parts.append("  (none)")
    else:
        parts.append(
            f"  {'symbol':<10}{'qty':>10}{'entry':>12}{'mark':>12}"
            f"{'notional':>12}{'unrealized':>14}"
        )
        for p in metrics["open_positions"]:
            parts.append(
                f"  {p['symbol']:<10}{p['qty']:>10.4f}{p['avg_entry']:>12.4f}"
                f"{p['mark']:>12.4f}{p['notional_usd']:>12.2f}"
                f"{p['unrealized_pnl_usd']:>+14.2f}"
            )

    # Last error
    parts.append("")
    parts.append("--- Last error since session start ---")
    if metrics["last_error"] is None:
        parts.append("  (none — clean run)")
    else:
        err = metrics["last_error"]
        msg = err["message"]
        if len(msg) > 200:
            msg = msg[:200] + "..."
        parts.append(f"  at={err['at']}  where={err['where']}")
        parts.append(f"  message={msg}")

    # Footer
    parts.append("")
    parts.append("=" * 72)
    parts.append(
        f"  refresh in {int(state.cutoff_at_utc.timestamp() - now.timestamp()):>6}s "
        f"to cutoff  |  Ctrl+C to exit (does NOT stop the session)"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _clear_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[2J\x1b[H")


def main() -> int:
    args = _parse_args()
    started_at, metadata = _resolve_started_at(args)
    cutoff_at = _parse_iso(args.cutoff)
    db_path = Path(args.db)
    log_path = Path(metadata.get("log_file") or DEFAULT_LOG)
    state = SessionState(
        started_at_utc=started_at,
        cutoff_at_utc=cutoff_at,
        db_path=db_path,
        log_path=log_path,
        metadata=metadata,
    )

    if args.once:
        print(_render(state))
        return 0

    try:
        while True:
            _clear_screen()
            sys.stdout.write(_render(state))
            sys.stdout.write("\n")
            sys.stdout.flush()
            time.sleep(max(2.0, float(args.refresh_seconds)))
    except KeyboardInterrupt:
        print("\nmonitor stopped (the underlying session is unaffected).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
