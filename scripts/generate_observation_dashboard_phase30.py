#!/usr/bin/env python3
"""Phase 30.2 — generate static observation ops dashboard (no external JS/CDN)."""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.overlay_observation_engine import PHASE28_TARGETS, default_state_dir

DEFAULT_BASE = REPO_ROOT / "reports" / "paper_observation_phase28"
DEFAULT_SUMMARY = REPO_ROOT / "reports" / "phase29_observation_metrics" / "summary.json"
DEFAULT_OUT = DEFAULT_BASE / "dashboard.html"


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows[-limit:]


def _read_equity(path: Path) -> list[tuple[int, float]]:
    if not path.is_file():
        return []
    rows: list[tuple[int, float]] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append((int(row["timestamp"]), float(row["equity"])))
    return rows


def _latest_ops_log(ops_logs: Path) -> tuple[str, str]:
    if not ops_logs.is_dir():
        return "", ""
    logs = sorted(ops_logs.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return "", ""
    latest = logs[0]
    text = latest.read_text(encoding="utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-8:])
    return latest.name, tail


def _verdict(summary: Mapping[str, Any], stop_active: bool) -> str:
    if stop_active:
        return "STOP — observation halted (STOP_OBSERVATION)"
    if summary.get("any_kill_triggered"):
        return "KILL — overlay kill criteria triggered; review before resume"
    return "CONTINUE — observation ops nominal; cron 4h VPS"


def _target_card(target: Mapping[str, Any]) -> str:
    eq = target.get("equity") or {}
    od = target.get("overlay_decisions") or {}
    kc = target.get("kill_criteria") or {}
    return f"""
    <div class="card">
      <h3>{_esc(target.get('target'))}</h3>
      <p class="muted">Decisions: {_esc(target.get('decision_count'))} |
      Trades: {_esc(target.get('trade_count'))} |
      Block rate: {_esc(target.get('block_rate_on_signals'))}</p>
      <p>Equity overlay: <strong>{_esc(eq.get('overlay_usd'))} USD</strong>
      ({_esc(eq.get('overlay_return_pct_from_1k'))}% from 1k)</p>
      <p>Overlay — allow {_esc(od.get('allow'))} |
      block {_esc(od.get('block'))} |
      reduce {_esc(od.get('reduce'))} |
      neutral {_esc(od.get('neutral'))}</p>
      <p>Kill: <span class="{'bad' if kc.get('should_kill') else 'ok'}">{_esc(kc.get('should_kill'))}</span>
      {_esc(', '.join(kc.get('reasons') or []))}</p>
    </div>"""


def _decisions_table(decisions: Sequence[Mapping[str, Any]]) -> str:
    if not decisions:
        return "<p class='muted'>No decisions yet.</p>"
    rows = []
    for d in reversed(decisions):
        rows.append(
            "<tr>"
            f"<td>{_esc(d.get('timestamp'))}</td>"
            f"<td>{_esc(d.get('raw_signal'))}</td>"
            f"<td>{_esc(d.get('overlay_decision'))}</td>"
            f"<td>{_esc(d.get('effective_action'))}</td>"
            f"<td>{_esc(d.get('funding_z'))}</td>"
            f"<td>{_esc(d.get('basis_z'))}</td>"
            f"<td>{_esc(d.get('equity'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>ts</th><th>raw</th><th>overlay</th><th>action</th>"
        "<th>f_z</th><th>b_z</th><th>equity</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _equity_bars(curves: Sequence[tuple[str, list[tuple[int, float]]]]) -> str:
    parts = []
    for name, rows in curves:
        if not rows:
            parts.append(f"<p class='muted'>{_esc(name)}: no equity curve</p>")
            continue
        vals = [eq for _, eq in rows]
        lo, hi = min(vals), max(vals)
        span = hi - lo or 1.0
        bars = []
        for ts, eq in rows[-12:]:
            pct = (eq - lo) / span * 100
            bars.append(
                f'<div class="bar" title="{_esc(ts)}: {eq:.2f}">'
                f'<div class="fill" style="height:{pct:.1f}%"></div></div>'
            )
        parts.append(
            f"<div class='eq-block'><h4>{_esc(name)}</h4>"
            f"<div class='bars'>{''.join(bars)}</div>"
            f"<p class='muted'>last={vals[-1]:.2f} USD</p></div>"
        )
    return "".join(parts)


def build_dashboard_html(
    *,
    observation_base: Path,
    summary_path: Path,
    generated_at: str | None = None,
) -> str:
    summary = _load_json(summary_path)
    stop_path = observation_base / "STOP_OBSERVATION"
    stop_active = stop_path.is_file()
    stop_reason = stop_path.read_text(encoding="utf-8").strip() if stop_active else ""

    targets = summary.get("targets") or []
    all_decisions: list[dict[str, Any]] = []
    equity_curves: list[tuple[str, list[tuple[int, float]]]] = []

    for strategy, variant, _ in PHASE28_TARGETS:
        state_dir = default_state_dir(observation_base, strategy, variant)
        all_decisions.extend(_load_jsonl(state_dir / "decisions.jsonl", limit=10))
        equity_curves.append((state_dir.name, _read_equity(state_dir / "equity_curve.csv")))

    log_name, log_tail = _latest_ops_log(observation_base / "ops_logs")
    gen = generated_at or datetime.now(UTC).isoformat()
    global_summary = summary.get("summary") or {}
    verdict = _verdict(global_summary, stop_active)

    target_cards = "".join(_target_card(t) for t in targets if isinstance(t, Mapping))

    stale_total = sum(int(t.get("stale_data_count") or 0) for t in targets if isinstance(t, Mapping))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Observation Ops Dashboard — Phase 30</title>
<style>
:root {{
  --bg: #0f1419; --panel: #1a2332; --text: #e7ecf3; --muted: #8b9cb3;
  --accent: #3d8bfd; --ok: #3dd68c; --warn: #ffb020; --bad: #ff6b6b;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: ui-sans-serif, system-ui, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.5; }}
header {{ padding: 1.25rem 1.5rem; border-bottom: 1px solid #2a3548; }}
header h1 {{ margin: 0 0 .25rem; font-size: 1.35rem; }}
.badge {{ display: inline-block; padding: .15rem .55rem; border-radius: 999px;
  font-size: .75rem; font-weight: 600; }}
.badge.ok {{ background: #1e3a2f; color: var(--ok); }}
.badge.bad {{ background: #3a1e1e; color: var(--bad); }}
.badge.warn {{ background: #3a2e1e; color: var(--warn); }}
main {{ padding: 1rem 1.5rem 2rem; max-width: 1100px; margin: 0 auto; }}
section {{ background: var(--panel); border-radius: 10px; padding: 1rem 1.1rem;
  margin-bottom: 1rem; border: 1px solid #2a3548; }}
section h2 {{ margin: 0 0 .75rem; font-size: 1rem; color: var(--accent); }}
.grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }}
.card {{ background: #121a26; border-radius: 8px; padding: .85rem; border: 1px solid #253044; }}
.card h3 {{ margin: 0 0 .5rem; font-size: .95rem; }}
.muted {{ color: var(--muted); font-size: .85rem; }}
.ok {{ color: var(--ok); }}
.bad {{ color: var(--bad); }}
table {{ width: 100%; border-collapse: collapse; font-size: .82rem; }}
th, td {{ border-bottom: 1px solid #2a3548; padding: .35rem .4rem; text-align: left; }}
pre {{ background: #0b1018; padding: .75rem; border-radius: 6px; overflow-x: auto;
  font-size: .75rem; color: var(--muted); }}
.bars {{ display: flex; align-items: flex-end; gap: 4px; height: 80px; }}
.bar {{ flex: 1; background: #253044; height: 100%; position: relative; border-radius: 3px; }}
.fill {{ position: absolute; bottom: 0; left: 0; right: 0; background: var(--accent);
  border-radius: 3px; min-height: 2px; }}
.eq-block {{ margin-bottom: .75rem; }}
.verdict {{ font-size: 1.05rem; font-weight: 600; }}
footer {{ padding: 1rem 1.5rem; color: var(--muted); font-size: .8rem; }}
</style>
</head>
<body>
<header>
  <h1>Overlay Paper Observation — Ops Dashboard</h1>
  <p class="muted">Phase 30.2 · PAPER ONLY · no live trading · generated {_esc(gen)} UTC</p>
  <span class="badge {'bad' if stop_active else 'ok'}">STOP: {'ACTIVE' if stop_active else 'absent'}</span>
  <span class="badge ok">observation_only</span>
</header>
<main>
  <section id="status">
    <h2>Status &amp; last run</h2>
    <p class="verdict">{_esc(verdict)}</p>
    <p>Summary generated: {_esc(summary.get('generated_at_utc'))}</p>
    <p>Last ops log: {_esc(log_name or 'none')}</p>
    <p>Targets: {_esc(global_summary.get('target_count'))} |
    Decisions: {_esc(global_summary.get('total_decisions'))} |
    Trades: {_esc(global_summary.get('total_trades'))}</p>
  </section>

  <section id="stop">
    <h2>STOP_OBSERVATION</h2>
    <p>Path: {_esc(stop_path)}</p>
    <p>Active: <strong class="{'bad' if stop_active else 'ok'}">{stop_active}</strong></p>
    {f'<p>Reason: {_esc(stop_reason)}</p>' if stop_active else '<p class="muted">Flag absent — daemon may run.</p>'}
  </section>

  <section id="freshness">
    <h2>Data freshness</h2>
    <p>Stale data signals (aggregate): <strong>{_esc(stale_total)}</strong></p>
    <p class="muted">Duplicate-candle skips are expected when cron runs before a new 4h bar closes.</p>
  </section>

  <section id="targets">
    <h2>Target cards</h2>
    <div class="grid">{target_cards or '<p class="muted">No target metrics — run aggregate_observation_metrics_phase29.py</p>'}</div>
  </section>

  <section id="equity">
    <h2>Equity comparison</h2>
    {_equity_bars(equity_curves)}
  </section>

  <section id="overlay">
    <h2>Overlay behavior</h2>
    <p class="muted">Block / reduce counts and shadow proxies from Phase 29 summary.json.</p>
    <ul>
      {''.join(
        f"<li>{_esc(t.get('target'))}: blocks={_esc((t.get('shadow_proxies') or {}).get('blocks'))}, "
        f"reductions={_esc((t.get('shadow_proxies') or {}).get('reductions'))}, "
        f"missed_upside={_esc((t.get('shadow_proxies') or {}).get('missed_upside_bars'))}</li>"
        for t in targets if isinstance(t, Mapping)
      ) or '<li class="muted">n/a</li>'}
    </ul>
  </section>

  <section id="risk">
    <h2>Risk metrics</h2>
    <ul>
      {''.join(
        f"<li>{_esc(t.get('target'))}: max_dd={_esc((t.get('equity') or {}).get('max_drawdown_pct'))}%, "
        f"errors={_esc(t.get('error_count'))}</li>"
        for t in targets if isinstance(t, Mapping)
      ) or '<li class="muted">n/a</li>'}
    </ul>
  </section>

  <section id="decisions">
    <h2>Recent decisions</h2>
    {_decisions_table(all_decisions[-15:])}
  </section>

  <section id="kill">
    <h2>Kill criteria</h2>
    <p class="muted">See reports/paper_observation_phase28/KILL_CRITERIA.md for thresholds.</p>
    <ul>
      {''.join(
        f"<li>{_esc(t.get('target'))}: should_kill={_esc((t.get('kill_criteria') or {}).get('should_kill'))}</li>"
        for t in targets if isinstance(t, Mapping)
      ) or '<li class="muted">n/a</li>'}
    </ul>
  </section>

  <section id="next">
    <h2>Next decision verdict</h2>
    <p class="verdict">{_esc(verdict)}</p>
    <p class="muted">Reference: reports/PHASE30_NEXT_DECISION.md · cron VPS unchanged.</p>
  </section>

  <section id="ops-log">
    <h2>Latest ops log tail</h2>
    <pre>{_esc(log_tail or 'No ops_logs yet.')}</pre>
  </section>
</main>
<footer>
  Static HTML — no external JS/CDN · open locally or copy to VPS ·
  regenerate: python scripts/generate_observation_dashboard_phase30.py
</footer>
</body>
</html>"""


def write_dashboard(
    out_path: Path,
    *,
    observation_base: Path = DEFAULT_BASE,
    summary_path: Path = DEFAULT_SUMMARY,
) -> Path:
    html_doc = build_dashboard_html(
        observation_base=observation_base,
        summary_path=summary_path,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 30.2 observation ops dashboard")
    p.add_argument("--observation-base", type=Path, default=DEFAULT_BASE)
    p.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    path = write_dashboard(
        args.out,
        observation_base=args.observation_base,
        summary_path=args.summary,
    )
    print(json.dumps({"dashboard": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
