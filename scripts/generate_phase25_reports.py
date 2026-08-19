#!/usr/bin/env python3
"""Generate Phase 25 markdown reports from autopsy JSON artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTOPSY_SUMMARY = REPO_ROOT / "reports" / "phase25_autopsy" / "summary.json"
AUTOPSY_FULL = REPO_ROOT / "reports" / "phase25_autopsy" / "full_results.json"


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def generate_all(reports_dir: Path) -> None:
    summary = _load_json(AUTOPSY_SUMMARY)
    full = _load_json(AUTOPSY_FULL)
    tests = full.get("tests", [])
    baseline = full.get("baseline", {})
    final = summary.get("final_verdict", "kill")
    pc = summary.get("paper_candidate_count", 0)

    test_table = "\n".join(
        f"| {t.get('test_id', '?')} | **{t.get('verdict', '?')}** | {t.get('summary', '')} |"
        for t in tests
    )

    autopsy_md = [
        "# Phase 25 — Candidate autopsy",
        "",
        f"**Cible :** `{summary.get('candidate_run_id', 'ETH_4h_trend_following_slow_off_h40_rolling')}`",
        "",
        f"## Verdict final : **{final}**",
        "",
        f"- `paper_observation_candidate_count` : **{pc}** (attendu 0 sauf passage intégral)",
        f"- Micro-live : **{summary.get('micro_live', 'NO-GO')}**",
        "",
        "## Baseline (re-run Phase 24 config)",
        "",
        f"- Excess vs B&H : **{baseline.get('excess_vs_bh_pct', 'n/a')}%**",
        f"- Max DD strat / B&H : **{baseline.get('max_drawdown_pct', 'n/a')}%** / "
        f"**{baseline.get('bh_max_drawdown_pct', 'n/a')}%**",
        f"- Trades : **{baseline.get('trade_count', 'n/a')}**",
        f"- Holdouts > B&H : **{baseline.get('holdout_beats_bh', 'n/a')}** / "
        f"**{baseline.get('windows_total', 'n/a')}**",
        "",
        "## Tests",
        "",
        "| Test | Verdict | Résumé |",
        "|------|---------|--------|",
        test_table,
        "",
        "## Critères passage (paper observation)",
        "",
        "Tous requis : reproductibilité, fees 40 bps, ±10% params, multi-période, "
        "pas de concentration trades, DD significativement < B&H, Calmar > B&H, red team OK.",
        "",
        "## Conclusion",
        "",
        _verdict_narrative(final),
        "",
    ]
    (reports_dir / "PHASE25_CANDIDATE_AUTOPSY.md").write_text(
        "\n".join(autopsy_md) + "\n", encoding="utf-8"
    )

    red = [
        "# Red team — Phase 25",
        "",
        "## Questions",
        "",
        "1. **Live / micro-live ?** Non — cache-only, NO-GO micro-live.",
        "2. **Fichiers interdits touchés ?** Non — execution/risk/futures/web/config intacts.",
        "3. **Nouvelle stratégie / tuning post-hoc ?** Non — trend_following slow ±10% seulement.",
        "4. **Reproductibilité Phase 24 ?** Voir test `reproducibility`.",
        "5. **Edge uniquement à frais bas ?** Voir `fee_sensitivity`.",
        "6. **Edge une seule période ?** Voir `period_splits`.",
        "7. **ETH 4h seul ?** Voir `asset_placebo`.",
        "8. **Trades concentrés ?** Voir `trade_concentration`.",
        "9. **DD justifie +0.14% excess ?** Voir `drawdown_acceptability`.",
        "",
        f"## Verdict red team : **{final}** — pas de promotion live.",
        "",
    ]
    (reports_dir / "RED_TEAM_PHASE25.md").write_text("\n".join(red) + "\n", encoding="utf-8")

    qa = [
        "# Final QA — Phase 25",
        "",
        f"- Final verdict : **{final}**",
        f"- Paper candidates : **{pc}**",
        f"- Tests run : **{len(tests)}**",
        "",
        "## Commandes",
        "",
        "```powershell",
        ".\\.venv\\Scripts\\Activate.ps1",
        "python scripts/run_candidate_autopsy_phase25.py",
        "python scripts/generate_phase25_reports.py",
        "python -m pytest -q tests/test_candidate_autopsy_phase25.py",
        "```",
        "",
    ]
    (reports_dir / "FINAL_QA_PHASE25.md").write_text("\n".join(qa) + "\n", encoding="utf-8")

    if final == "paper_observation_candidate":
        phase26 = (
            "**Phase 26A** — Paper observation daemon 2–4 semaines (cache/sim), "
            "jamais live xStocks/crypto sans nouveau compte."
        )
    elif final == "weak":
        phase26 = (
            "**Phase 26B** — Kill paper path ; option recherche (cache étendu, "
            "autres holdout %) ou derivatives research hors scope live EU."
        )
    else:
        phase26 = (
            "**Phase 26B** — Kill candidat ; documenter échec honnête ; "
            "pas de paper/live. Option : étendre données ou revoir hypothèses low-freq."
        )

    next_dec = [
        "# Phase 25 — Next decision",
        "",
        "## Recommandation Phase 26",
        "",
        phase26,
        "",
        f"- Autopsy verdict : **{final}**",
        f"- `paper_candidate_count` : **{pc}**",
        "",
    ]
    (reports_dir / "PHASE25_NEXT_DECISION.md").write_text(
        "\n".join(next_dec) + "\n", encoding="utf-8"
    )

    micro = [
        "# Micro-live GO/NO-GO — Phase 25",
        "",
        "## Verdict : **NO-GO**",
        "",
        "- Compte PEDSL-CY : xStocks spot/perps API-blocked.",
        f"- Autopsy final : **{final}** (pas de candidat paper robuste).",
        "- Même `paper_observation_candidate` n'autorise **pas** le micro-live.",
        "",
    ]
    (reports_dir / "MICRO_LIVE_GO_NO_GO_PHASE25.md").write_text(
        "\n".join(micro) + "\n", encoding="utf-8"
    )


def _verdict_narrative(final: str) -> str:
    if final == "paper_observation_candidate":
        return (
            "Le candidat passe tous les filtres Phase 25. Prochaine étape : "
            "**paper observation only** (Phase 26A), sans live."
        )
    if final == "weak":
        return (
            "Validation fragile (souvent ETH 4h seul). **Pas de paper** — "
            "documentation `weak` et arrêt de la piste micro-live."
        )
    return (
        "Le candidat ne survit pas l'autopsie ultra-stricte. **Kill** — "
        "ne pas activer paper observation ni live."
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Phase 25 reports")
    p.add_argument("--reports-dir", type=Path, default=REPO_ROOT / "reports")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    generate_all(args.reports_dir)
    print(json.dumps({"reports_dir": str(args.reports_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
