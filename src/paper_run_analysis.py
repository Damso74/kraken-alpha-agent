"""Pure analytics for paper / dry-run sessions.

The companion script (``scripts/analyze_paper_run.py``) only handles the
filesystem I/O and Markdown rendering; everything quantitative lives here
so it can be unit-tested without writing files.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .utils import safe_float


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    raw = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _within_window(at: str | None, cutoff: datetime) -> bool:
    parsed = _parse_iso(at)
    if parsed is None:
        return True  # keep records whose timestamp we cannot parse
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed >= cutoff


@dataclass
class PaperRunReport:
    generated_at: str
    since_hours: float
    profile: str | None
    cycles_count: int = 0
    cycles_avg_duration_ms: float = 0.0
    decisions_count: int = 0
    actions_distribution: dict[str, int] = field(default_factory=dict)
    execution_statuses: dict[str, int] = field(default_factory=dict)
    top_symbols: list[dict[str, Any]] = field(default_factory=list)
    pnl_realized_usd: float = 0.0
    pnl_unrealized_usd: float = 0.0
    pnl_net_usd: float = 0.0
    equity_last_usd: float = 0.0
    fifo_trades: list[dict[str, Any]] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    errors_by_source: dict[str, int] = field(default_factory=dict)
    opportunity_score_stats: dict[str, float] = field(default_factory=dict)
    actionability_reasons: dict[str, int] = field(default_factory=dict)
    no_data: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "since_hours": self.since_hours,
            "profile": self.profile,
            "no_data": self.no_data,
            "cycles_count": self.cycles_count,
            "cycles_avg_duration_ms": self.cycles_avg_duration_ms,
            "decisions_count": self.decisions_count,
            "actions_distribution": self.actions_distribution,
            "execution_statuses": self.execution_statuses,
            "top_symbols": self.top_symbols,
            "pnl_realized_usd": self.pnl_realized_usd,
            "pnl_unrealized_usd": self.pnl_unrealized_usd,
            "pnl_net_usd": self.pnl_net_usd,
            "equity_last_usd": self.equity_last_usd,
            "fifo_trades": self.fifo_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "errors_by_source": self.errors_by_source,
            "opportunity_score_stats": self.opportunity_score_stats,
            "actionability_reasons": self.actionability_reasons,
            "notes": self.notes,
        }


def _safe_load_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return {}


def _fifo_pnl(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair BUY → SELL by FIFO per symbol, return realised trades."""
    per_symbol: dict[str, list[dict[str, Any]]] = {}
    trades: list[dict[str, Any]] = []
    # Process orders chronologically.
    for row in sorted(orders, key=lambda r: r.get("at") or ""):
        payload = _safe_load_json(row.get("payload_json"))
        status = row.get("status") or payload.get("status")
        if status not in ("paper_filled", "live_filled"):
            continue
        symbol = row.get("symbol") or payload.get("symbol")
        if not symbol:
            continue
        action = (row.get("action") or payload.get("action") or "").upper()
        volume = safe_float(payload.get("volume") or payload.get("filled_volume"))
        price = safe_float(payload.get("fill_price") or payload.get("price"))
        fee = safe_float(payload.get("fee"))
        if volume <= 0 or price <= 0:
            continue
        bucket = per_symbol.setdefault(symbol, [])
        if action == "BUY":
            bucket.append({"qty": volume, "price": price, "fee": fee, "at": row.get("at")})
            continue
        if action != "SELL":
            continue
        remaining = volume
        realised = 0.0
        legs: list[dict[str, Any]] = []
        while remaining > 1e-9 and bucket:
            head = bucket[0]
            take = min(head["qty"], remaining)
            realised += (price - head["price"]) * take
            legs.append({
                "qty": take, "entry": head["price"], "exit": price,
                "entry_at": head["at"], "exit_at": row.get("at"),
            })
            head["qty"] -= take
            remaining -= take
            if head["qty"] <= 1e-9:
                bucket.pop(0)
        if legs:
            realised -= fee
            trades.append({
                "symbol": symbol,
                "exit_at": row.get("at"),
                "qty": sum(leg["qty"] for leg in legs),
                "pnl_usd": realised,
                "legs": legs,
            })
    return trades


def compute_report(
    *,
    decisions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    pnl_snapshots: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    since_hours: float,
    profile: str | None,
    generated_at: str,
) -> PaperRunReport:
    cutoff = datetime.now(UTC) - timedelta(hours=since_hours)
    f_decisions = [d for d in decisions if _within_window(d.get("at"), cutoff)]
    f_orders = [o for o in orders if _within_window(o.get("at"), cutoff)]
    f_cycles = [c for c in cycles if _within_window(c.get("started_at"), cutoff)]
    f_errors = [e for e in errors if _within_window(e.get("at"), cutoff)]
    f_pnl = [p for p in pnl_snapshots if _within_window(p.get("at"), cutoff)]

    report = PaperRunReport(
        generated_at=generated_at,
        since_hours=since_hours,
        profile=profile,
    )
    if not (f_decisions or f_orders or f_pnl or f_cycles):
        report.no_data = True
        report.notes.append(
            "No paper run data yet — run `python scripts/run_agent_loop.py` "
            "in paper or dry_run mode first."
        )
        return report

    # Cycles.
    report.cycles_count = len(f_cycles)
    durations = [safe_float(c.get("duration_ms")) for c in f_cycles if c.get("duration_ms")]
    if durations:
        report.cycles_avg_duration_ms = sum(durations) / len(durations)

    # Decisions.
    report.decisions_count = len(f_decisions)
    actions: dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
    scores: list[float] = []
    actionability_reasons: dict[str, int] = {}
    for d in f_decisions:
        act = (d.get("action") or "HOLD").upper()
        actions[act] = actions.get(act, 0) + 1
        scores.append(safe_float(d.get("final_score")))
        payload = _safe_load_json(d.get("payload_json"))
        actionability = payload.get("actionability") if isinstance(payload, dict) else None
        if isinstance(actionability, dict):
            reason = str(actionability.get("reason") or "n/a")
            actionability_reasons[reason] = actionability_reasons.get(reason, 0) + 1
    report.actions_distribution = actions
    report.actionability_reasons = dict(
        sorted(actionability_reasons.items(), key=lambda kv: kv[1], reverse=True)
    )
    if scores:
        report.opportunity_score_stats = {
            "count": float(len(scores)),
            "mean": sum(scores) / len(scores),
            "min": min(scores),
            "max": max(scores),
            "stdev": statistics.pstdev(scores) if len(scores) > 1 else 0.0,
            "positive_ratio": sum(1 for s in scores if s > 0) / len(scores),
        }

    # Orders.
    statuses: dict[str, int] = {}
    symbol_counts: dict[str, int] = {}
    for o in f_orders:
        status = str(o.get("status") or "")
        statuses[status] = statuses.get(status, 0) + 1
        sym = o.get("symbol")
        if sym:
            symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
    report.execution_statuses = statuses
    report.top_symbols = [
        {"symbol": s, "orders": n}
        for s, n in sorted(symbol_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]

    # PnL.
    if f_pnl:
        last = sorted(f_pnl, key=lambda p: p.get("at") or "")[-1]
        report.pnl_realized_usd = safe_float(last.get("realized_usd"))
        report.pnl_unrealized_usd = safe_float(last.get("unrealized_usd"))
        report.pnl_net_usd = safe_float(last.get("net_usd"))
        report.equity_last_usd = safe_float(last.get("equity_usd"))

    # FIFO win/loss.
    fifo_trades = _fifo_pnl(f_orders)
    report.fifo_trades = fifo_trades
    report.wins = sum(1 for t in fifo_trades if t["pnl_usd"] > 0)
    report.losses = sum(1 for t in fifo_trades if t["pnl_usd"] < 0)
    decided = report.wins + report.losses
    report.win_rate = (report.wins / decided) if decided else 0.0

    # Errors.
    err_by_source: dict[str, int] = {}
    for e in f_errors:
        src = str(e.get("where_label") or e.get("source") or "unknown")
        err_by_source[src] = err_by_source.get(src, 0) + 1
    report.errors_by_source = dict(
        sorted(err_by_source.items(), key=lambda kv: kv[1], reverse=True)
    )

    return report


def render_markdown(report: PaperRunReport) -> str:
    if report.no_data:
        return (
            f"# Paper Run Report — {report.generated_at}\n\n"
            f"_Window: last {report.since_hours:g}h, profile: {report.profile or '-'}_\n\n"
            "**No paper run data yet.** Run a dry-run or paper loop first:\n\n"
            "```\npython scripts/run_agent_loop.py\n```\n"
        )

    lines: list[str] = [
        f"# Paper Run Report — {report.generated_at}",
        "",
        f"_Window: last {report.since_hours:g}h · profile: **{report.profile or '-'}**_",
        "",
        "## Executive summary",
        f"- Cycles: **{report.cycles_count}** (avg duration {report.cycles_avg_duration_ms:.0f} ms)",
        f"- Decisions: **{report.decisions_count}** "
        f"(BUY={report.actions_distribution.get('BUY', 0)}, "
        f"SELL={report.actions_distribution.get('SELL', 0)}, "
        f"HOLD={report.actions_distribution.get('HOLD', 0)})",
        f"- FIFO trades: **{len(report.fifo_trades)}** "
        f"(wins {report.wins}, losses {report.losses}, win-rate {report.win_rate * 100:.1f}%)",
        f"- PnL net (last snapshot): **${report.pnl_net_usd:,.2f}** "
        f"(realized ${report.pnl_realized_usd:,.2f} · "
        f"unrealized ${report.pnl_unrealized_usd:,.2f})",
        f"- Equity last: ${report.equity_last_usd:,.2f}",
        f"- Errors: {sum(report.errors_by_source.values())} "
        f"across {len(report.errors_by_source)} sources",
        "",
        "## Execution statuses",
    ]
    if report.execution_statuses:
        lines.append("| status | count |")
        lines.append("|---|---:|")
        for status, count in sorted(report.execution_statuses.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {status} | {count} |")
    else:
        lines.append("_No orders in this window._")
    lines.append("")

    lines.append("## Top symbols")
    if report.top_symbols:
        lines.append("| symbol | orders |")
        lines.append("|---|---:|")
        for row in report.top_symbols:
            lines.append(f"| {row['symbol']} | {row['orders']} |")
    else:
        lines.append("_No symbol activity._")
    lines.append("")

    lines.append("## Opportunity score distribution")
    if report.opportunity_score_stats:
        s = report.opportunity_score_stats
        lines.append(
            f"- count {s['count']:.0f} · mean {s['mean']:+.3f} · "
            f"min {s['min']:+.3f} · max {s['max']:+.3f} · "
            f"stdev {s['stdev']:.3f} · positive_ratio {s['positive_ratio'] * 100:.1f}%"
        )
    else:
        lines.append("_No decisions recorded._")
    lines.append("")

    lines.append("## Actionability outcomes")
    if report.actionability_reasons:
        lines.append("| reason | count |")
        lines.append("|---|---:|")
        for reason, count in report.actionability_reasons.items():
            lines.append(f"| {reason} | {count} |")
    else:
        lines.append("_No actionability annotations in this window._")
    lines.append("")

    lines.append("## FIFO trades (most recent first)")
    if report.fifo_trades:
        lines.append("| exit_at | symbol | qty | pnl_usd |")
        lines.append("|---|---|---:|---:|")
        for t in sorted(report.fifo_trades, key=lambda x: x.get("exit_at") or "", reverse=True)[:20]:
            lines.append(
                f"| {t['exit_at']} | {t['symbol']} | {t['qty']:.6f} | {t['pnl_usd']:+.2f} |"
            )
    else:
        lines.append("_No realised round-trip trades._")
    lines.append("")

    lines.append("## Errors by source")
    if report.errors_by_source:
        lines.append("| source | count |")
        lines.append("|---|---:|")
        for src, count in report.errors_by_source.items():
            lines.append(f"| {src} | {count} |")
    else:
        lines.append("_No errors recorded._")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["PaperRunReport", "compute_report", "render_markdown"]
