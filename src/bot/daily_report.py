"""Daily paper trading report generator (Phase 19)."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


@dataclass
class DailyReportData:
    report_date: str
    equity: float
    pnl_day: float
    open_positions: list[dict[str, Any]]
    risk_denials: int
    trades: list[dict[str, Any]]
    drawdown_pct: float
    errors: list[str]
    next_action: str


def _read_equity_curve(state_dir: Path) -> list[tuple[str, float]]:
    path = state_dir / "equity_curve.csv"
    if not path.is_file():
        return []
    rows: list[tuple[str, float]] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append((row["timestamp"], float(row["equity"])))
    return rows


def _read_trades(state_dir: Path) -> list[dict[str, Any]]:
    path = state_dir / "trades.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _read_errors(state_dir: Path) -> list[str]:
    path = state_dir / "errors.log"
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").strip().splitlines()[-10:]


def build_daily_report(state_dir: Path | str, *, report_date: date | None = None) -> DailyReportData:
    root = Path(state_dir)
    rd = report_date or datetime.now(UTC).date()
    state_raw: dict[str, Any] = {}
    sp = root / "state.json"
    if sp.is_file():
        state_raw = json.loads(sp.read_text(encoding="utf-8"))

    equity_rows = _read_equity_curve(root)
    equity = float(state_raw.get("equity", 1000.0))
    pnl_day = 0.0
    if len(equity_rows) >= 2:
        pnl_day = equity_rows[-1][1] - equity_rows[-2][1]
        equity = equity_rows[-1][1]

    positions: list[dict[str, Any]] = []
    pp = root / "positions.json"
    if pp.is_file():
        positions = list(json.loads(pp.read_text(encoding="utf-8")).values())

    trades = _read_trades(root)
    errors = _read_errors(root)

    peak = equity
    dd = 0.0
    for _, eq in equity_rows:
        peak = max(peak, eq)
        if peak > 0:
            dd = max(dd, (peak - eq) / peak * 100.0)

    mode = state_raw.get("mode", "observation")
    next_action = "continue_paper_observation" if mode == "observation" else "review_signals"

    return DailyReportData(
        report_date=rd.isoformat(),
        equity=equity,
        pnl_day=pnl_day,
        open_positions=positions,
        risk_denials=0,
        trades=trades[-20:],
        drawdown_pct=dd,
        errors=errors,
        next_action=next_action,
    )


def render_daily_report_md(data: DailyReportData) -> str:
    lines = [
        f"# Paper daily summary — {data.report_date}",
        "",
        "> **PAPER ONLY — no live trading.**",
        "",
        f"- Equity: **{data.equity:.2f}** USD",
        f"- PnL day: {data.pnl_day:+.2f} USD",
        f"- Drawdown (curve): {data.drawdown_pct:.2f}%",
        f"- Open positions: {len(data.open_positions)}",
        f"- Recent trades: {len(data.trades)}",
        f"- Errors (tail): {len(data.errors)}",
        f"- Next action: {data.next_action}",
        "",
    ]
    if data.errors:
        lines.append("## Recent errors")
        for e in data.errors:
            lines.append(f"- `{e}`")
        lines.append("")
    return "\n".join(lines)


def write_daily_report(state_dir: Path | str, output_dir: Path | str) -> Path:
    data = build_daily_report(state_dir)
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / f"daily_summary_{data.report_date}.md"
    path.write_text(render_daily_report_md(data), encoding="utf-8")
    return path


def build_overlay_observation_report(
    state_dir: Path | str,
    *,
    report_date: date | None = None,
) -> dict[str, Any]:
    """Phase 28 overlay observation daily metrics."""
    from src.bot.overlay_shadow_compare import load_shadow_comparisons, summarize_shadow

    root = Path(state_dir)
    rd = report_date or datetime.now(UTC).date()
    base = build_daily_report(root, report_date=rd)
    shadows = load_shadow_comparisons(root)
    today_rows = [r for r in shadows if str(r.get("timestamp", "")).startswith(str(rd))]
    if not today_rows and shadows:
        today_rows = shadows[-5:]
    summary = summarize_shadow(shadows)
    last = shadows[-1] if shadows else {}
    return {
        "report_date": rd.isoformat(),
        "equity": base.equity,
        "pnl_day": base.pnl_day,
        "drawdown_pct": base.drawdown_pct,
        "raw_signal": last.get("raw_signal", "n/a"),
        "overlay_decision": last.get("overlay_decision", "n/a"),
        "overlay_reason": last.get("overlay_reason", ""),
        "funding_z": last.get("funding_z"),
        "basis_z": last.get("basis_z"),
        "blocks_total": summary["blocks"],
        "reductions_total": summary["reductions"],
        "block_rate": summary["block_rate_on_signals"],
        "shadow_rows_today": len(today_rows),
        "errors": base.errors,
        "open_positions": base.open_positions,
    }


def render_overlay_observation_md(data: Mapping[str, Any]) -> str:
    lines = [
        f"# Overlay observation daily — {data['report_date']}",
        "",
        "> **PAPER OBSERVATION ONLY — no live trading, no Kraken private API.**",
        "",
        "## Signal & overlay",
        f"- Raw signal: `{data.get('raw_signal', 'n/a')}`",
        f"- Overlay decision: `{data.get('overlay_decision', 'n/a')}`",
        f"- Overlay reason: {data.get('overlay_reason', '')}",
        f"- Funding z: {data.get('funding_z')}",
        f"- Basis z: {data.get('basis_z')}",
        "",
        "## Paper portfolio",
        f"- Equity: **{data.get('equity', 0):.2f}** USD",
        f"- PnL day: {data.get('pnl_day', 0):+.2f} USD",
        f"- Drawdown (curve): {data.get('drawdown_pct', 0):.2f}%",
        f"- Open positions: {len(data.get('open_positions', []))}",
        "",
        "## Shadow comparison (cumulative)",
        f"- Blocks: {data.get('blocks_total', 0)}",
        f"- Reductions: {data.get('reductions_total', 0)}",
        f"- Block rate on standalone signals: {data.get('block_rate', 0):.2%}",
        f"- Shadow rows today: {data.get('shadow_rows_today', 0)}",
        "",
    ]
    errors = data.get("errors") or []
    if errors:
        lines.append("## Stale / errors")
        for e in errors:
            lines.append(f"- `{e}`")
        lines.append("")
    return "\n".join(lines)


def write_overlay_observation_report(
    state_dir: Path | str,
    output_dir: Path | str,
    *,
    report_date: date | None = None,
) -> Path:
    data = build_overlay_observation_report(state_dir, report_date=report_date)
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / f"daily_summary_{data['report_date']}.md"
    path.write_text(render_overlay_observation_md(data), encoding="utf-8")
    return path


def write_weekly_overlay_report(
    state_dirs: Sequence[Path | str],
    output_dir: Path | str,
    *,
    week_label: str | None = None,
) -> Path:
    rd = datetime.now(UTC).date()
    iso = rd.isocalendar()
    label = week_label or f"{iso.year}-W{iso.week:02d}"
    sections: list[str] = [
        f"# Overlay observation weekly — {label}",
        "",
        "> **PAPER OBSERVATION ONLY.**",
        "",
    ]
    for sd in state_dirs:
        data = build_overlay_observation_report(sd)
        name = Path(sd).name
        sections.append(f"## {name}")
        sections.append(f"- Equity: {data['equity']:.2f} USD")
        sections.append(f"- Blocks: {data['blocks_total']} | Reductions: {data['reductions_total']}")
        sections.append(f"- Block rate: {data['block_rate']:.2%}")
        sections.append("")
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / f"weekly_summary_{label}.md"
    path.write_text("\n".join(sections), encoding="utf-8")
    return path
