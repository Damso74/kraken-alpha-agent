"""Daily paper trading report generator (Phase 19)."""

from __future__ import annotations

import csv
import json
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
