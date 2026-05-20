#!/usr/bin/env python3
"""Phase 22 — strategy family autopsy report generator."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase22_common import (  # noqa: E402
    FAMILY_LABELS,
    PHASE21_TOURNAMENT,
    PHASE21_WALKFORWARD,
    STRATEGY_FAMILIES,
    aggregate_by_family,
    load_json_runs,
    strategy_family,
)

VERDICT_OPTIONS = (
    "kill",
    "keep_for_tuning",
    "keep_as_overlay",
    "needs_different_timeframe",
    "too_costly",
    "too_unstable",
)


def _family_verdict(fam: str, tour_stats: dict, wf_stats: dict, fee_stats: dict) -> tuple[str, str]:
    """Return (verdict, rationale) — diagnostic only, no tuning claims."""
    runs = tour_stats.get("runs", 0)

    if fam == "vol_targeting":
        return "keep_as_overlay", "overlay not exercised in Phase 21 baseline (vol_targeting=off)"

    if fam == "regime_router":
        return (
            "keep_as_overlay",
            "1d return +50% but blocked_risk; overlay/risk-reduction only (see regime_router_perf)",
        )

    if runs == 0:
        return "kill", "no runs"

    pc = tour_stats.get("paper_candidate_count", 0)
    br = tour_stats.get("blocked_risk_count", 0)
    bc = tour_stats.get("blocked_costs_count", 0)
    it = tour_stats.get("insufficient_trades_count", 0)
    med_trades = tour_stats.get("median_trades", 0)
    med_ret = tour_stats.get("median_return_pct", 0)
    unstable = wf_stats.get("unstable_count", 0)
    weak = wf_stats.get("weak_count", 0)
    wf_total = wf_stats.get("runs", 0)
    no_edge = fee_stats.get("no_edge_at_zero_fees", 0)
    killed_costs = fee_stats.get("killed_by_costs", 0)

    if pc > 0:
        return "keep_for_tuning", f"{pc} paper_candidate in tournament (verify walk-forward)"

    if wf_total and unstable >= wf_total * 0.5:
        return "too_unstable", f"walk-forward unstable {unstable}/{wf_total}"

    if bc >= runs // 2 or killed_costs >= fee_stats.get("total", 1) // 2:
        return "too_costly", f"blocked_costs={bc}/{runs}, fee grid killed_by_costs={killed_costs}"

    if it >= runs // 2 and med_trades < 5:
        return "needs_different_timeframe", f"insufficient_trades={it}/{runs}, median trades={med_trades}"

    if br >= runs // 3:
        return "kill", f"blocked_risk={br}/{runs}, median return={med_ret:.1f}%"

    if no_edge >= fee_stats.get("total", 1) * 0.6:
        return "kill", f"no edge at 0 bps in {no_edge} fee-grid cells"

    if weak > 0 and med_ret > -5:
        return "keep_for_tuning", f"weak but not catastrophic (median {med_ret:.1f}%)"

    return "kill", f"median return {med_ret:.1f}%, no paper_candidate"


def _wf_by_family(wf_runs: list[dict]) -> dict[str, dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in wf_runs:
        buckets[strategy_family(str(row.get("strategy", "")))].append(row)
    out = {}
    for fam, items in buckets.items():
        verdicts = [str(r.get("verdict", "")) for r in items]
        out[fam] = {
            "runs": len(items),
            "unstable_count": sum(1 for v in verdicts if v == "unstable"),
            "weak_count": sum(1 for v in verdicts if v == "weak"),
            "paper_candidate_count": sum(1 for v in verdicts if "paper_candidate" in v),
        }
    return out


def _fee_by_family(fee_summary: dict) -> dict[str, dict]:
    per = fee_summary.get("per_strategy", [])
    buckets: dict[str, list[str]] = defaultdict(list)
    for item in per:
        fam = strategy_family(str(item.get("strategy", "")))
        buckets[fam].append(str(item.get("interpretation", "")))
    out = {}
    for fam, labels in buckets.items():
        counts: dict[str, int] = defaultdict(int)
        for label in labels:
            counts[label] += 1
        out[fam] = {"total": len(labels), **dict(counts)}
    return out


def generate_autopsy(
    *,
    tournament_path: Path,
    walkforward_path: Path,
    fee_summary_path: Path,
) -> str:
    tour_runs = load_json_runs(tournament_path)
    wf_runs = load_json_runs(walkforward_path)
    fee_summary = {}
    if fee_summary_path.is_file():
        fee_summary = json.loads(fee_summary_path.read_text(encoding="utf-8"))

    tour_by_fam = aggregate_by_family(tour_runs)
    wf_by_fam = _wf_by_family(wf_runs)
    fee_by_fam = _fee_by_family(fee_summary)

    lines = [
        "# Strategy family autopsy — Phase 22",
        "",
        "Diagnostic verdicts only — **not** tuning recommendations.",
        "",
        "| Family | Verdict | Tournament | Walk-forward | Fee grid | Rationale |",
        "|--------|---------|------------|--------------|----------|-----------|",
    ]

    all_families = list(STRATEGY_FAMILIES.keys())
    for fam in all_families:
        label = FAMILY_LABELS.get(fam, fam)
        ts = tour_by_fam.get(fam, {})
        ws = wf_by_fam.get(fam, {})
        fs = fee_by_fam.get(fam, {})
        verdict, rationale = _family_verdict(fam, ts, ws, fs)
        tour_cell = f"pc={ts.get('paper_candidate_count', 0)} br={ts.get('blocked_risk_count', 0)} it={ts.get('insufficient_trades_count', 0)}"
        wf_cell = f"unstable={ws.get('unstable_count', 0)} weak={ws.get('weak_count', 0)}"
        fee_cell = f"no_edge={fs.get('no_edge_at_zero_fees', 0)} costly={fs.get('killed_by_costs', 0)}"
        lines.append(f"| {label} | **{verdict}** | {tour_cell} | {wf_cell} | {fee_cell} | {rationale} |")

    lines.extend(
        [
            "",
            "## Verdict legend",
            "",
            "- `kill` — no evidence of edge under current rules",
            "- `keep_for_tuning` — marginal signal; Phase 23 may explore params (not post-hoc save)",
            "- `keep_as_overlay` — vol targeting / router overlay only",
            "- `needs_different_timeframe` — sparse trades on 1d, wrong freq on 1h",
            "- `too_costly` — turnover eats gross at realistic fees",
            "- `too_unstable` — walk-forward windows disagree",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Generate strategy family autopsy (Phase 22)")
    p.add_argument("--tournament", type=Path, default=PHASE21_TOURNAMENT / "results.json")
    p.add_argument("--walkforward", type=Path, default=PHASE21_WALKFORWARD / "results.json")
    p.add_argument(
        "--fee-summary",
        type=Path,
        default=REPO_ROOT / "reports" / "fee_sensitivity_phase22" / "summary.json",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "reports" / "strategy_family_autopsy_phase22.md",
    )
    args = p.parse_args()
    text = generate_autopsy(
        tournament_path=args.tournament,
        walkforward_path=args.walkforward,
        fee_summary_path=args.fee_summary,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
