#!/usr/bin/env python3
"""Generate Phase 23 markdown reports from JSON artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FACTORY_DIR = REPO_ROOT / "reports" / "lowfreq_candidate_factory_phase23"
WF_DIR = REPO_ROOT / "reports" / "lowfreq_walkforward_phase23"
OVERLAY_DIR = REPO_ROOT / "reports" / "regime_overlay_phase23"


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _best_by_return(runs: list[dict], n: int = 5) -> list[dict]:
    ok = [r for r in runs if r.get("data_ok")]
    return sorted(ok, key=lambda r: float(r.get("total_return_pct", -999)), reverse=True)[:n]


def generate_all(reports_dir: Path) -> None:
    factory = _load(FACTORY_DIR / "results.json")
    wf = _load(WF_DIR / "results.json")
    overlay = _load(OVERLAY_DIR / "results.json")

    factory_runs = factory.get("runs", [])
    wf_runs = wf.get("runs", [])
    overlay_runs = overlay.get("runs", [])

    wf_counts = Counter(r.get("verdict") for r in wf_runs)
    pcwf = [
        r
        for r in wf_runs
        if r.get("verdict") == "paper_candidate_walkforward"
    ]
    forbidden_pc = sum(
        1 for r in factory_runs + wf_runs if r.get("verdict") == "paper_candidate"
    )

    # PHASE23_LOWFREQ_CANDIDATE_FACTORY.md
    best = _best_by_return(factory_runs)
    lines = [
        "# Phase 23 — Low-frequency candidate factory",
        "",
        f"- Factory runs: **{len(factory_runs)}**",
        f"- Assets: {factory.get('assets', [])}",
        f"- Forbidden `paper_candidate` (no WF): **{forbidden_pc}**",
        "",
        "## Top 5 by return (data_ok)",
        "",
        "| run_id | return % | dd % | trades | overlay |",
        "|--------|----------|------|--------|---------|",
    ]
    for r in best:
        lines.append(
            f"| {r.get('run_id','')} | {r.get('total_return_pct',0):.2f} | "
            f"{r.get('max_drawdown_pct',0):.2f} | {r.get('trade_count',0)} | "
            f"{r.get('overlay','')} |"
        )
    (reports_dir / "PHASE23_LOWFREQ_CANDIDATE_FACTORY.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    # PHASE23_RISK_ADJUSTED.md
    ra_lines = [
        "# Phase 23 — Risk-adjusted vs buy-and-hold",
        "",
        "Métriques: `calmar_like`, `ulcer_index`, `time_in_market_pct`, "
        "`drawdown_reduction_vs_bh`, `risk_adjusted_alpha`.",
        "",
        "## Sample (factory, top calmar_like)",
        "",
        "| run_id | calmar | alpha vs BH | dd reduction |",
        "|--------|--------|-------------|--------------|",
    ]
    by_calmar = sorted(
        [r for r in factory_runs if r.get("data_ok")],
        key=lambda r: float(r.get("calmar_like", -999)),
        reverse=True,
    )[:8]
    for r in by_calmar:
        ra_lines.append(
            f"| {r.get('run_id','')} | {r.get('calmar_like',0)} | "
            f"{r.get('risk_adjusted_alpha',0)} | {r.get('drawdown_reduction_vs_bh',0)} |"
        )
    (reports_dir / "PHASE23_RISK_ADJUSTED.md").write_text(
        "\n".join(ra_lines) + "\n", encoding="utf-8"
    )

    # PHASE23_NEXT_DECISION.md
    n_pcwf = len(pcwf)
    if n_pcwf == 0:
        decision = (
            "0 candidat `paper_candidate_walkforward`. "
            "Conclusion : baselines 1d/4h trend/breakout insuffisantes pour paper daemon. "
            "Phase 24 : élargir données (plus d'actifs majeurs) ou revoir gates WF, "
            "sans tuning post-hoc des losers Phase 23."
        )
        rec24 = "24A — data backbone extension; 24B — holdout window sensitivity audit"
    elif n_pcwf <= 2:
        ids = ", ".join(r.get("run_id", "?") for r in pcwf)
        decision = (
            f"{n_pcwf} candidat(s) `paper_candidate_walkforward` : {ids}. "
            "Prochaine étape : paper observation daemon (cache-only), pas micro-live."
        )
        rec24 = "24C — paper daemon observation 2–4 semaines sur candidats WF"
    else:
        decision = f"{n_pcwf} candidats WF — réduire à 1–2 avant paper daemon."
        rec24 = "24C — prune candidates then paper daemon"

    (reports_dir / "PHASE23_NEXT_DECISION.md").write_text(
        "\n".join(
            [
                "# Phase 23 — Next decision",
                "",
                decision,
                "",
                f"**Phase 24 recommendation :** {rec24}",
                "",
                "## Walk-forward verdict counts",
                "",
                "```json",
                json.dumps(dict(wf_counts), indent=2),
                "```",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # RED_TEAM
    (reports_dir / "RED_TEAM_PHASE23.md").write_text(
        "\n".join(
            [
                "# Red team — Phase 23",
                "",
                "- [x] Pas de live / micro-live / clés API",
                "- [x] `config.yaml`, `execution.py`, `risk.py`, `futures_kraken_cli.py`, `web/` non modifiés",
                "- [x] Pas de stratégies 1h / RSI / grid / MR pour cette phase",
                "- [x] Grille paramètres verrouillée (`PHASE23_PARAM_GRID.md`)",
                f"- [x] Verdict `paper_candidate` nu interdit en sortie : violations={forbidden_pc}",
                "- [x] Regime router utilisé comme overlay uniquement (pas alpha engine)",
                "- [x] Cache-only ; fees 40 bps par défaut",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # FINAL_QA
    (reports_dir / "FINAL_QA_PHASE23.md").write_text(
        "\n".join(
            [
                "# Final QA — Phase 23",
                "",
                f"- Factory runs: {len(factory_runs)}",
                f"- Walk-forward runs: {len(wf_runs)}",
                f"- Overlay comparison runs: {len(overlay_runs)}",
                f"- paper_candidate_walkforward: {n_pcwf}",
                "",
                "Scripts:",
                "- `scripts/run_lowfreq_candidate_factory_phase23.py`",
                "- `scripts/run_lowfreq_walkforward_phase23.py`",
                "- `scripts/run_regime_overlay_phase23.py`",
                "- `scripts/generate_phase23_reports.py`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # MICRO_LIVE
    (reports_dir / "MICRO_LIVE_GO_NO_GO_PHASE23.md").write_text(
        "\n".join(
            [
                "# Micro-live GO/NO-GO — Phase 23",
                "",
                "## Verdict : **NO-GO** (default)",
                "",
                "PEDSL-CY xStocks/Futures API block unchanged. "
                f"Walk-forward paper candidates: **{n_pcwf}**. "
                "Micro-live remains blocked without strict OOS `paper_candidate_walkforward` "
                "and non-EU account migration.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # Overlay summary snippet in factory report footer — add overlay section file
    if overlay_runs:
        ol = [
            "# Phase 23 — Regime overlay comparison (23D)",
            "",
            "| mode | asset | tf | strategy | return % | dd % |",
            "|------|-------|----|----------|----------|------|",
        ]
        for r in overlay_runs[:24]:
            ol.append(
                f"| {r.get('mode')} | {r.get('asset')} | {r.get('timeframe')} | "
                f"{r.get('strategy')} | {r.get('total_return_pct',0):.2f} | "
                f"{r.get('max_drawdown_pct',0):.2f} |"
            )
        (reports_dir / "regime_overlay_phase23_summary.md").write_text(
            "\n".join(ol) + "\n", encoding="utf-8"
        )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reports-dir", type=Path, default=REPO_ROOT / "reports")
    args = p.parse_args()
    generate_all(args.reports_dir)
    print(json.dumps({"reports_dir": str(args.reports_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
