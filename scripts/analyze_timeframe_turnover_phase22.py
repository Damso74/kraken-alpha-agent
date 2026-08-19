#!/usr/bin/env python3
"""Phase 22 — timeframe × turnover analysis from Phase 21 + cache runs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import median
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase22_common import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    PHASE21_TOURNAMENT,
    load_json_runs,
    resolve_grid,
    run_backtest_cell,
    strategy_family,
    write_matrix_csv,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 22 timeframe turnover analysis")
    p.add_argument(
        "--input",
        type=Path,
        default=PHASE21_TOURNAMENT / "results.json",
        help="Phase 21 tournament results (fallback if missing turnover)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "timeframe_turnover_phase22",
    )
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument(
        "--refresh-turnover",
        action="store_true",
        help="Re-run baseline backtests to compute turnover_ratio",
    )
    p.add_argument("--fast", action="store_true", help="BTC only for refresh")
    return p.parse_args()


COST_DRAG_UNDEFINED_KEY = "cost_drag_undefined"


def cost_drag_stats(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Mediane du cost drag calculee sur les seuls runs ou il est mesurable.

    ``src.bot.metrics`` ne renvoie plus la sentinelle 100 % quand aucun
    aller-retour n'a ete ferme : il met ``cost_drag_undefined`` a vrai et
    laisse ``cost_drag_pct`` a 0.0 en remplissage. Agreger ce 0.0 dirait
    "les frais ne coutent rien", ce qui est plus trompeur encore que
    l'ancien 100 %. Ces runs sont donc exclus de la mediane, et comptes.

    Un run qui ne porte pas du tout la cle ``cost_drag_undefined`` (artefact
    JSON produit avant le correctif, ou constructeur de ligne qui ne propage
    pas encore le drapeau) est lui aussi exclu : son ``cost_drag_pct`` peut
    etre soit une mesure, soit l'ancienne sentinelle, et rien dans la ligne
    ne permet de trancher. Il est compte separement pour que le rapport le
    dise au lieu de le noyer dans la mediane.
    """
    measurable: list[float] = []
    undefined = 0
    unflagged = 0
    for row in items:
        if COST_DRAG_UNDEFINED_KEY not in row:
            unflagged += 1
        elif bool(row[COST_DRAG_UNDEFINED_KEY]):
            undefined += 1
        else:
            measurable.append(float(row.get("cost_drag_pct", 0.0)))
    return {
        "median_cost_drag_pct": median(measurable) if measurable else None,
        "cost_drag_runs_total": len(items),
        "cost_drag_measurable_runs": len(measurable),
        "cost_drag_undefined_runs": undefined,
        "cost_drag_unflagged_runs": unflagged,
    }


def format_cost_drag_line(stats: Mapping[str, Any]) -> str:
    """Ligne markdown du cost drag, denominateur de la mediane explicite."""
    total = int(stats.get("cost_drag_runs_total", 0))
    kept = int(stats.get("cost_drag_measurable_runs", 0))
    undefined = int(stats.get("cost_drag_undefined_runs", 0))
    unflagged = int(stats.get("cost_drag_unflagged_runs", 0))
    excluded: list[str] = []
    if undefined:
        excluded.append(f"{undefined} runs sans aller-retour ferme (cost drag indefini)")
    if unflagged:
        excluded.append(f"{unflagged} runs sans indicateur `{COST_DRAG_UNDEFINED_KEY}`")
    detail = f"median calculee sur {kept}/{total} runs"
    if excluded:
        detail += "; exclus: " + ", ".join(excluded)
    value = stats.get("median_cost_drag_pct")
    if value is None:
        return f"- Median cost drag: n/a — aucun run mesurable ({detail})"
    return f"- Median cost drag: {float(value):.1f}% ({detail})"


def _aggregate_by_timeframe(rows: list[dict]) -> dict[str, dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get("timeframe", "1d"))].append(row)

    out: dict[str, dict] = {}
    for tf, items in sorted(buckets.items()):
        returns = [float(r.get("total_return_pct", 0)) for r in items]
        trades = [int(r.get("trade_count", 0)) for r in items]
        turnover = [float(r.get("turnover_ratio", 0)) for r in items]
        verdicts = [str(r.get("verdict", "")) for r in items]
        out[tf] = {
            "runs": len(items),
            "median_return_pct": median(returns) if returns else 0.0,
            "median_trades": median(trades) if trades else 0,
            **cost_drag_stats(items),
            "median_turnover_ratio": median(turnover) if turnover else 0.0,
            "paper_candidate_count": sum(1 for v in verdicts if v == "paper_candidate"),
            "blocked_costs_count": sum(1 for v in verdicts if v == "blocked_costs"),
            "blocked_risk_count": sum(1 for v in verdicts if v == "blocked_risk"),
            "insufficient_trades_count": sum(1 for v in verdicts if v == "insufficient_trades"),
        }
    return out


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = load_json_runs(args.input)
    if args.refresh_turnover or not rows or "turnover_ratio" not in rows[0]:
        assets = ["BTC"] if args.fast else ["BTC", "ETH", "SOL"]
        timeframes = ["1d"] if args.fast else ["1d", "4h", "1h"]
        grid = resolve_grid(assets, timeframes)
        rows = [
            run_backtest_cell(a, tf, s, fees_bps=40.0, slippage_bps=5.0, cache_root=args.cache_root)
            for a, tf, s in grid
        ]

    by_tf = _aggregate_by_timeframe(rows)
    by_family_tf: dict[str, dict[str, dict]] = defaultdict(dict)
    fam_buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        fam = strategy_family(str(row.get("strategy", "")))
        tf = str(row.get("timeframe", "1d"))
        fam_buckets[(fam, tf)].append(row)
    for (fam, tf), items in fam_buckets.items():
        by_family_tf[fam][tf] = {
            "median_trades": median([int(r.get("trade_count", 0)) for r in items]),
            "median_return_pct": median([float(r.get("total_return_pct", 0)) for r in items]),
            **cost_drag_stats(items),
        }

    summary = {
        "source": str(args.input),
        "by_timeframe": by_tf,
        "by_family_timeframe": {k: v for k, v in by_family_tf.items()},
        "interpretation": {
            "1d": "Low turnover, often insufficient_trades — signals too sparse",
            "4h": "Higher activity; mix of blocked_risk and blocked_costs",
            "1h": "Highest turnover; cost drag dominates, negative median returns",
        },
    }

    (args.output_dir / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_matrix_csv(args.output_dir / "runs.csv", rows)

    md = ["# Timeframe × turnover — Phase 22", ""]
    for tf, stats in by_tf.items():
        md.append(f"## {tf}")
        md.append(f"- Median trades: {stats['median_trades']:.1f}")
        md.append(f"- Median return: {stats['median_return_pct']:.2f}%")
        md.append(format_cost_drag_line(stats))
        md.append(f"- Paper candidates: {stats['paper_candidate_count']}")
        md.append("")
    (args.output_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps({"output_dir": str(args.output_dir), "timeframes": list(by_tf)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
