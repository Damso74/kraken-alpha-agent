"""Export the live xStocks dry-run shadow session into the submission JSON.

Reads ``data/agent.sqlite`` (filtered by the session start timestamp from
``data/shadow_session.json`` or ``--since``) and writes
``web/public/data/shadow_session.json`` with a schema that matches the
existing backtest snapshots, plus an explicit ``mode: "live_shadow_dry_run"``
flag so the submission UI can label the panel honestly.

This script is **read-only with respect to the live session** but it
should NOT be invoked while the launcher is still running, to avoid a
race condition with SQLite WAL writes. Stop the launcher (Ctrl+C) before
running this exporter.

Usage::

    python scripts/export_shadow_session_for_submission.py
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB = ROOT / "data" / "agent.sqlite"
DEFAULT_METADATA = ROOT / "data" / "shadow_session.json"
DEFAULT_OUT = ROOT / "web" / "public" / "data" / "shadow_session.json"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Export the live xStocks dry-run shadow session into "
            "web/public/data/shadow_session.json. Run AFTER stopping "
            "the launcher (Ctrl+C in its window)."
        )
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
        help="path to data/shadow_session.json (written by the launcher).",
    )
    p.add_argument(
        "--since",
        type=str,
        default=None,
        help="explicit session start UTC ISO-8601, overrides --metadata.",
    )
    p.add_argument(
        "--until",
        type=str,
        default=None,
        help=(
            "explicit session end UTC ISO-8601 (defaults to now). "
            "Useful when re-exporting an older session."
        ),
    )
    p.add_argument(
        "--out",
        type=str,
        default=str(DEFAULT_OUT),
        help="output JSON path.",
    )
    p.add_argument(
        "--starting-capital",
        type=float,
        default=100.0,
        help=(
            "starting USD capital reference for the equity curve "
            "(default 100, mirrors the shadow_xstocks_36h cap)."
        ),
    )
    p.add_argument(
        "--profile",
        type=str,
        default="shadow_xstocks_36h",
        help="profile label exposed in the JSON (default shadow_xstocks_36h).",
    )
    p.add_argument(
        "--print-summary",
        action="store_true",
        help="print a short ASCII summary block suitable for the demo video.",
    )
    p.add_argument(
        "--update-docs",
        action="store_true",
        help=(
            "splice/refresh the shadow-session block in README.md and "
            "docs/SUBMISSION.md (between the BEGIN/END markers). Off by "
            "default so smoke runs do not pollute the docs."
        ),
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime:
    s = ts.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_window(args: argparse.Namespace) -> tuple[datetime, datetime, dict[str, Any]]:
    """Return ``(started_at_utc, ended_at_utc, metadata)``."""
    metadata: dict[str, Any] = {}
    metadata_path = Path(args.metadata)
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
    if args.since:
        started = _parse_iso(args.since)
    elif metadata.get("started_at_utc"):
        started = _parse_iso(metadata["started_at_utc"])
    else:
        raise SystemExit(
            "ERROR: cannot resolve session start. Pass --since or run the "
            "launcher so it writes data/shadow_session.json."
        )
    if args.until:
        ended = _parse_iso(args.until)
    else:
        ended = _now_utc()
    if ended <= started:
        raise SystemExit(
            f"ERROR: ended_at <= started_at ({_iso(ended)} <= {_iso(started)})"
        )
    return started, ended, metadata


# ---------------------------------------------------------------------------
# DB extraction
# ---------------------------------------------------------------------------


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"ERROR: agent SQLite DB not found at {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _extract_session(
    db_path: Path, *, started_iso: str, ended_iso: str
) -> dict[str, Any]:
    """Pull cycles, decisions, orders and pnl_snapshots into memory."""
    conn = _connect_ro(db_path)
    try:
        cycles = [
            dict(r)
            for r in conn.execute(
                "SELECT id, started_at, finished_at, mode, symbols_seen, "
                "       decisions, approved, errors, summary_json "
                "FROM cycles WHERE started_at >= ? AND started_at <= ? "
                "ORDER BY started_at",
                (started_iso, ended_iso),
            ).fetchall()
        ]
        decisions = [
            dict(r)
            for r in conn.execute(
                "SELECT id, at, symbol, action, final_score, confidence, "
                "       suggested_size_usd, approved_size_usd, regime, mode, "
                "       approved, rationale "
                "FROM decisions WHERE at >= ? AND at <= ? ORDER BY at",
                (started_iso, ended_iso),
            ).fetchall()
        ]
        orders = [
            dict(r)
            for r in conn.execute(
                "SELECT at, mode, status, symbol, action, requested_size_usd, "
                "       filled_size_usd, fill_price, volume, fee, order_id, error "
                "FROM orders WHERE at >= ? AND at <= ? ORDER BY at",
                (started_iso, ended_iso),
            ).fetchall()
        ]
        pnl_snapshots = [
            dict(r)
            for r in conn.execute(
                "SELECT at, realized_usd, unrealized_usd, net_usd, equity_usd, "
                "       drawdown_pct "
                "FROM pnl_snapshots WHERE at >= ? AND at <= ? ORDER BY at",
                (started_iso, ended_iso),
            ).fetchall()
        ]
        errors = [
            dict(r)
            for r in conn.execute(
                "SELECT at, where_label, message FROM errors "
                "WHERE at >= ? AND at <= ? ORDER BY at",
                (started_iso, ended_iso),
            ).fetchall()
        ]
    finally:
        conn.close()
    return {
        "cycles": cycles,
        "decisions": decisions,
        "orders": orders,
        "pnl_snapshots": pnl_snapshots,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# FIFO trade pairing — same logic as export_submission_backtest._pair_trades
# but applied to the dry_run_logged orders stream.
# ---------------------------------------------------------------------------


def _pair_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FIFO pair BUY → SELL orders from the simulated dry-run stream."""
    open_buys: dict[str, list[dict[str, Any]]] = defaultdict(list)
    paired: list[dict[str, Any]] = []
    # Restrict to mutating actions in dry_run mode (status=dry_run_logged).
    relevant = [
        o
        for o in orders
        if o.get("mode") == "dry_run"
        and o.get("status") == "dry_run_logged"
        and (o.get("action") or "").upper() in ("BUY", "SELL")
    ]
    for o in relevant:
        sym = o.get("symbol") or "?"
        action = (o.get("action") or "").upper()
        if action == "BUY":
            open_buys[sym].append(dict(o))
            continue
        if not open_buys[sym]:
            continue
        entry = open_buys[sym].pop(0)
        try:
            ts_in = _parse_iso(entry["at"])
            ts_out = _parse_iso(o["at"])
            duration_min = max(0, int((ts_out - ts_in).total_seconds() // 60))
        except (KeyError, ValueError, TypeError):
            duration_min = None
        qty = float(entry.get("volume") or 0.0)
        entry_price = float(entry.get("fill_price") or 0.0)
        exit_price = float(o.get("fill_price") or 0.0)
        size_usd = float(entry.get("filled_size_usd") or 0.0) or qty * entry_price
        # PnL = (exit - entry) * qty - fees(both legs)
        fee_in = float(entry.get("fee") or 0.0)
        fee_out = float(o.get("fee") or 0.0)
        gross = (exit_price - entry_price) * qty
        pnl_usd = gross - fee_in - fee_out
        paired.append(
            {
                "ts": entry.get("at"),
                "exit_ts": o.get("at"),
                "symbol": sym,
                "action": "BUY",
                "size_usd": round(size_usd, 4),
                "qty": round(qty, 6),
                "fill_price": round(entry_price, 6),
                "exit_price": round(exit_price, 6),
                "exit_reason": o.get("error") or "simulated_fill",
                "fee_in_usd": round(fee_in, 6),
                "fee_out_usd": round(fee_out, 6),
                "pnl_usd": round(pnl_usd, 4),
                "pnl_pct": round(
                    (pnl_usd / size_usd * 100.0) if size_usd > 0 else 0.0, 4
                ),
                "duration_min": duration_min,
            }
        )
    paired.sort(key=lambda t: t.get("ts") or "")
    return paired


# ---------------------------------------------------------------------------
# Equity curve from pnl_snapshots
# ---------------------------------------------------------------------------


def _build_equity_curve(
    pnl_snapshots: list[dict[str, Any]], *, starting_capital: float
) -> list[dict[str, Any]]:
    """Normalise the pnl_snapshots stream into [{ts, equity_usd}, ...].

    The pnl module persists ``net_usd`` as cumulative session PnL (see
    src/pnl.py). The equity at time t is therefore
    ``starting_capital + net_usd``.
    """
    if not pnl_snapshots:
        return []
    out: list[dict[str, Any]] = []
    for snap in pnl_snapshots:
        try:
            ts = _parse_iso(snap["at"])
        except (KeyError, ValueError):
            continue
        equity = starting_capital + float(snap.get("net_usd") or 0.0)
        out.append({"ts": _iso(ts), "equity_usd": round(equity, 4)})
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _by_symbol_summary(
    paired: list[dict[str, Any]], *, decisions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for p in paired:
        sym = p["symbol"]
        d = seen.setdefault(
            sym,
            {
                "symbol": sym,
                "trades_count": 0,
                "buy_count": 0,
                "sell_count": 0,
                "wins": 0,
                "losses": 0,
                "net_pnl_usd": 0.0,
                "net_pnl_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "last_price": 0.0,
            },
        )
        d["trades_count"] += 1
        d["buy_count"] += 1
        d["sell_count"] += 1
        if p["pnl_usd"] >= 0:
            d["wins"] += 1
        else:
            d["losses"] += 1
        d["net_pnl_usd"] = round(d["net_pnl_usd"] + p["pnl_usd"], 4)
        d["last_price"] = p["exit_price"]
    # also surface symbols that had decisions but no closed pair
    for dec in decisions:
        sym = dec.get("symbol")
        if not sym or sym in seen:
            continue
        seen[sym] = {
            "symbol": sym,
            "trades_count": 0,
            "buy_count": 0,
            "sell_count": 0,
            "wins": 0,
            "losses": 0,
            "net_pnl_usd": 0.0,
            "net_pnl_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "last_price": 0.0,
        }
    return sorted(seen.values(), key=lambda r: r["symbol"])


def _build_payload(
    *,
    started: datetime,
    ended: datetime,
    starting_capital: float,
    profile: str,
    metadata: dict[str, Any],
    rows: dict[str, Any],
) -> dict[str, Any]:
    paired = _pair_orders(rows["orders"])
    equity_curve = _build_equity_curve(
        rows["pnl_snapshots"], starting_capital=starting_capital
    )

    total_pnl = sum(p["pnl_usd"] for p in paired)
    final_equity = (
        equity_curve[-1]["equity_usd"]
        if equity_curve
        else starting_capital + total_pnl
    )
    wins = sum(1 for p in paired if p["pnl_usd"] >= 0)
    losses = sum(1 for p in paired if p["pnl_usd"] < 0)
    fees_total = sum(p.get("fee_in_usd", 0.0) + p.get("fee_out_usd", 0.0) for p in paired)
    by_symbol_rows = _by_symbol_summary(paired, decisions=rows["decisions"])
    universe = sorted({r["symbol"] for r in by_symbol_rows})

    pnls = [p["pnl_usd"] for p in paired]
    if len(pnls) >= 2:
        mean = sum(pnls) / len(pnls)
        var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        per_trade_sharpe = round(mean / std, 4) if std > 0 else None
    else:
        per_trade_sharpe = None

    duration_seconds = max(1, int((ended - started).total_seconds()))
    duration_hours = round(duration_seconds / 3600.0, 2)

    cycles = rows["cycles"]
    cycles_dry_run = sum(1 for c in cycles if c.get("mode") == "dry_run")
    cycles_total = len(cycles)
    decisions_total = len(rows["decisions"])
    decisions_approved = sum(1 for d in rows["decisions"] if d.get("approved"))

    payload = {
        "generated_at": _iso(_now_utc()),
        "mode": "live_shadow_dry_run",
        "engine": "dry_run",
        "profile": profile,
        "source": "live_shadow_session",
        "session": {
            "started_at_utc": _iso(started),
            "ended_at_utc": _iso(ended),
            "duration_hours": duration_hours,
            "cycles_total": cycles_total,
            "cycles_dry_run": cycles_dry_run,
            "decisions_total": decisions_total,
            "decisions_approved": decisions_approved,
            "loop_interval_s": metadata.get("loop_interval_s"),
            "log_file": metadata.get("log_file"),
            "pid": metadata.get("pid"),
        },
        "period": {
            "start": started.date().isoformat(),
            "end": ended.date().isoformat(),
            "days": max(1, math.ceil(duration_seconds / 86400.0)),
            "hours": duration_hours,
        },
        "universe": universe,
        "summary": {
            "starting_capital_usd": round(starting_capital, 4),
            "ending_capital_usd": round(final_equity, 4),
            "total_pnl_usd": round(total_pnl, 4),
            "total_pnl_pct": round(
                (total_pnl / starting_capital * 100.0) if starting_capital > 0 else 0.0,
                4,
            ),
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "total_trades": len(paired),
            "buy_count": len(paired),
            "sell_count": len(paired),
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": round((wins / max(1, wins + losses)), 4) if paired else 0.0,
            "per_trade_sharpe": per_trade_sharpe,
            "fees_total_usd": round(fees_total, 4),
            "snapshot_label": "live_shadow_dry_run",
        },
        "by_symbol": by_symbol_rows,
        "equity_curve": equity_curve,
        "trades": paired,
        "errors": rows["errors"],
        "rejections": {
            "live_xstocks_spot": "EGeneral:Permission denied (PEDSL-CY)",
            "live_xstocks_perps": (
                "wouldNotReducePosition (every BUY/SELL rejected, "
                "even without --reduce-only)"
            ),
            "btc_perp_control": "status:placed (proves API/key/futures routing OK)",
            "account_class": "PEDSL-CY (Cyprus EU)",
            "verified_at": "2026-05-15",
        },
        "notes": [
            (
                "live_shadow_dry_run: real-time Kraken xStocks tickers polled in "
                "dry_run mode. NO order ever leaves the process — defended by the "
                "src/execution._assert_not_dry_run tripwire and the triple "
                "TRADING_MODE / LIVE_TRADING / ALLOW_LIVE_ORDERS env-flag block."
            ),
            (
                "PEDSL-CY (Cyprus EU) account-class blocks both spot and futures "
                "xStocks orderbooks. The shadow session simulates execution "
                "structurally identical to what the live engine would do, "
                "without the venue-side rejection."
            ),
            "Equity curve is sampled from src.pnl snapshots (one per cycle).",
            "Trade pairs are FIFO-matched BUY → SELL inside each symbol.",
        ],
    }
    return payload


# ---------------------------------------------------------------------------
# ASCII summary for the demo video
# ---------------------------------------------------------------------------


def _ascii_summary(payload: dict[str, Any]) -> str:
    s = payload["summary"]
    sess = payload["session"]
    lines: list[str] = []
    lines.append("+" + "-" * 70 + "+")
    lines.append(
        f"|  KRAKEN ALPHA AGENT — LIVE SHADOW DRY-RUN  ({sess['duration_hours']:>5.1f}h){' ' * (70 - 60)}|"
    )
    lines.append("+" + "-" * 70 + "+")
    lines.append(
        f"|  started   : {sess['started_at_utc']:<24}"
        f"  cycles : {sess['cycles_dry_run']:<6}|"
    )
    lines.append(
        f"|  ended     : {sess['ended_at_utc']:<24}"
        f"  decisions : {sess['decisions_total']:<3}|"
    )
    lines.append(f"|  universe  : {payload['universe']}")
    lines.append("|" + " " * 70 + "|")
    lines.append(
        f"|  pnl_total : {s['total_pnl_usd']:+9.4f} USD ({s['total_pnl_pct']:+.4f}%)"
        f"  trades : {s['total_trades']:<5}|"
    )
    lines.append(
        f"|  win_rate  : {s['win_rate'] * 100:5.2f}%"
        f"  fees   : {s['fees_total_usd']:+.4f} USD               |"
    )
    lines.append(
        f"|  capital   : {s['starting_capital_usd']:.2f} -> {s['ending_capital_usd']:.2f} USD"
        + " " * 12
        + "|"
    )
    lines.append("+" + "-" * 70 + "+")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# README / SUBMISSION updates
# ---------------------------------------------------------------------------


_README_MARKER_BEGIN = "<!-- BEGIN:shadow-session -->"
_README_MARKER_END = "<!-- END:shadow-session -->"
_SUBMISSION_MARKER_BEGIN = "<!-- BEGIN:shadow-session -->"
_SUBMISSION_MARKER_END = "<!-- END:shadow-session -->"


def _render_shadow_block(payload: dict[str, Any]) -> str:
    sess = payload["session"]
    s = payload["summary"]
    return (
        f"{_README_MARKER_BEGIN}\n"
        f"### Real-time Shadow Session — Hackathon Window (May 18-20, 2026)\n\n"
        f"- **Mode**: `live_shadow_dry_run` — real Kraken xStocks tickers, "
        f"deterministic ensemble + risk gates running every "
        f"{sess.get('loop_interval_s', '?')}s, **no live order placed** "
        f"(triple env block + `_assert_not_dry_run` tripwire).\n"
        f"- **Window**: `{sess['started_at_utc']} → {sess['ended_at_utc']}` "
        f"({sess['duration_hours']:.1f}h, {sess['cycles_dry_run']} cycles)\n"
        f"- **Universe**: {payload['universe']}\n"
        f"- **Decisions**: {sess['decisions_total']} total / "
        f"{sess['decisions_approved']} approved by the risk gate\n"
        f"- **Simulated trades**: {s['total_trades']} pairs "
        f"(win_rate={s['win_rate'] * 100:.2f}%, "
        f"fees={s['fees_total_usd']:+.4f} USD)\n"
        f"- **Net session PnL**: **{s['total_pnl_usd']:+.4f} USD** "
        f"({s['total_pnl_pct']:+.4f}% on a {s['starting_capital_usd']:.0f} USD "
        f"reference cap)\n"
        f"- **Snapshot**: "
        f"[`web/public/data/shadow_session.json`](web/public/data/shadow_session.json)\n"
        f"{_README_MARKER_END}"
    )


def _splice_marker_block(text: str, *, begin: str, end: str, block: str) -> str:
    if begin in text and end in text:
        before, _, rest = text.partition(begin)
        _, _, after = rest.partition(end)
        return f"{before}{block}{after}"
    return f"{text.rstrip()}\n\n{block}\n"


def _maybe_update_doc(path: Path, payload: dict[str, Any]) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    block = _render_shadow_block(payload)
    new_text = _splice_marker_block(
        text, begin=_README_MARKER_BEGIN, end=_README_MARKER_END, block=block
    )
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    args = _parse_args()
    started, ended, metadata = _resolve_window(args)
    rows = _extract_session(
        Path(args.db),
        started_iso=_iso(started),
        ended_iso=_iso(ended),
    )
    payload = _build_payload(
        started=started,
        ended=ended,
        starting_capital=float(args.starting_capital),
        profile=str(args.profile),
        metadata=metadata,
        rows=rows,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    readme_updated = False
    submission_updated = False
    if args.update_docs:
        readme_updated = _maybe_update_doc(ROOT / "README.md", payload)
        submission_updated = _maybe_update_doc(ROOT / "docs" / "SUBMISSION.md", payload)

    print(f"shadow session exported -> {out_path}")
    print(
        f"  cycles_dry_run={payload['session']['cycles_dry_run']}  "
        f"trades={payload['summary']['total_trades']}  "
        f"net_pnl={payload['summary']['total_pnl_usd']:+.4f} USD  "
        f"win_rate={payload['summary']['win_rate'] * 100:.2f}%"
    )
    if not args.update_docs:
        print(
            "  (--update-docs not set; README.md and docs/SUBMISSION.md left "
            "untouched. Pass --update-docs on the final run after stopping the "
            "session.)"
        )
    if readme_updated:
        print("  README.md   shadow section updated")
    if submission_updated:
        print("  docs/SUBMISSION.md shadow section updated")
    if args.print_summary:
        print()
        print(_ascii_summary(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
