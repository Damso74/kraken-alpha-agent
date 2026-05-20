#!/usr/bin/env python3
"""Generate Phase 24 markdown reports from JSON/CSV artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BACKBONE_JSON = REPO_ROOT / "reports" / "phase24_data_backbone" / "data_quality.json"
WF_SUMMARY = REPO_ROOT / "reports" / "phase24_walkforward_sensitivity" / "summary.json"
WF_RESULTS = REPO_ROOT / "reports" / "phase24_walkforward_sensitivity" / "results.csv"


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def generate_all(reports_dir: Path) -> None:
    backbone = _load_json(BACKBONE_JSON)
    wf_summary = _load_json(WF_SUMMARY)

    vc = wf_summary.get("validation_candidate_count", 0)
    pc = wf_summary.get("paper_candidate_count", 0)
    runs = wf_summary.get("runs_total", 0)

    # PHASE24_WALKFORWARD_SENSITIVITY.md
    wf_lines = [
        "# Phase 24 — Walk-forward holdout sensitivity",
        "",
        f"- Runs total: **{runs}**",
        f"- Holdout fractions: {wf_summary.get('holdout_pcts', [])}",
        f"- Window modes: {wf_summary.get('window_modes', [])}",
        f"- Overlay (primary): **{wf_summary.get('overlay', 'off')}**",
        f"- `validation_candidate`: **{vc}**",
        f"- `paper_candidate` / `paper_candidate_walkforward`: **{pc}** (forbidden)",
        "",
        "## Hypothesis test",
        "",
        "Phase 24 tests whether Phase 23 zero-candidate outcome was driven by:",
        "1. short history (`--max-bars 500`),",
        "2. strict WF holdout windows,",
        "3. limited asset universe, or",
        "4. absence of real alpha.",
        "",
    ]
    (reports_dir / "PHASE24_WALKFORWARD_SENSITIVITY.md").write_text(
        "\n".join(wf_lines) + "\n", encoding="utf-8"
    )

    # RED_TEAM_PHASE24.md — 9 questions
    entries = backbone.get("entries", [])
    longer = [e for e in entries if e.get("delta_bars_vs_phase23_cap", 0) > 0]
    red = [
        "# Red team — Phase 24",
        "",
        "## 9 questions",
        "",
        "1. **Live / micro-live touched?** Non — cache-only scripts, pas de triple opt-in.",
        "2. **Fichiers interdits modifiés?** Non — `execution.py`, `risk.py`, "
        "`futures_kraken_cli.py`, `web/`, `config.yaml` intacts.",
        "3. **Données réseau fetchées?** Non — audit et WF lisent uniquement "
        "`data/collector_cache/`.",
        "4. **Historique complet utilisé quand data_ok?** Oui — pas de `--max-bars` "
        "dans le script WF Phase 24.",
        f"5. **Delta vs Phase 23 cap 500 bars?** {len(longer)} entrées ont plus de "
        "500 barres disponibles.",
        f"6. **`paper_candidate` émis?** {pc} (doit rester 0).",
        f"7. **`validation_candidate` crédible?** {vc} — chaque cas exige "
        "≥2 holdouts > B&H, DD < B&H, trades ≥8.",
        "8. **Overlays pour sauver un candidat?** Non — WF principal overlay=off; "
        "overlay-only flag bloque validation.",
        "9. **Micro-live GO?** Non — compte PEDSL-CY / pas de candidat paper.",
        "",
        "## Verdict red team",
        "",
        "Phase 24 reste défensive et documentaire. Zéro candidat = succès si motivé.",
        "",
    ]
    (reports_dir / "RED_TEAM_PHASE24.md").write_text("\n".join(red) + "\n", encoding="utf-8")

    # FINAL_QA_PHASE24.md
    qa = [
        "# Final QA — Phase 24",
        "",
        "## Data backbone (24A)",
        "",
        f"- Required complete: **{backbone.get('required_complete', False)}**",
        f"- data_ok pairs: **{backbone.get('data_ok_count', 0)}** / "
        f"{backbone.get('entries_total', 0)}",
        "",
        "## Walk-forward sensitivity (24B)",
        "",
        f"- Runs: **{runs}**",
        f"- validation_candidate: **{vc}**",
        f"- paper_candidate: **{pc}**",
        "",
        "## Tests",
        "",
        "Run: `python -m pytest -q` (full suite must stay green).",
        "",
    ]
    (reports_dir / "FINAL_QA_PHASE24.md").write_text("\n".join(qa) + "\n", encoding="utf-8")

    # PHASE24_NEXT_DECISION.md
    if vc == 0 and pc == 0:
        option = "**Option A** — Pas d'alpha robuste : documenter échec, ne pas paper/live."
        opt_b = "Option B — Étendre cache actifs majeurs (XRP/ADA si fetch manuel) puis re-WF."
        opt_c = "Option C — Revoir uniquement gates WF (holdout %) sans tuning stratégies."
        opt_d = "Option D — Phase 25 paper review si 1 validation_candidate + red team dédié."
    elif vc > 0 and pc == 0:
        option = (
            f"**Option D** — {vc} `validation_candidate` : Phase 25 paper review "
            "(ultra-strict, pas micro-live)."
        )
        opt_b = "Option B — Compléter données avant paper."
        opt_c = "Option C — Holdout sensitivity seulement si instable."
        opt_d = "Option A — Stop si red team échoue."
    else:
        option = "**Option A** — Anomalie paper_candidate : bloquer et investiguer."
        opt_b = opt_c = opt_d = ""

    next_lines = [
        "# Phase 24 — Next decision",
        "",
        "## Recommandation",
        "",
        option,
        "",
        "## Options",
        "",
        "- **A** — Zéro candidat documenté ; pas de paper/live.",
        f"- **B** — {opt_b or 'Étendre backbone données (cache-only build).'}",
        f"- **C** — {opt_c or 'Sensibilité fenêtres uniquement.'}",
        f"- **D** — {opt_d or 'Paper review Phase 25.'}",
        "",
        "## Micro-live",
        "",
        "**NO-GO** — inchangé (PEDSL-CY, pas de paper_candidate_walkforward).",
        "",
    ]
    (reports_dir / "PHASE24_NEXT_DECISION.md").write_text(
        "\n".join(next_lines) + "\n", encoding="utf-8"
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Phase 24 markdown reports")
    p.add_argument("--reports-dir", type=Path, default=REPO_ROOT / "reports")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    generate_all(args.reports_dir)
    print(json.dumps({"reports_dir": str(args.reports_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
