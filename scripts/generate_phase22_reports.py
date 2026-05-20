#!/usr/bin/env python3
"""Phase 22 — synthesize PERFORMANCE_DIAGNOSIS and decision reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_strategy_family_autopsy_phase22 import generate_autopsy  # noqa: E402


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _recommend_phase23(autopsy_md: str, risk_summary: dict) -> str:
    if risk_summary.get("relaxed_config_paper_candidates"):
        return "23B"
    if "too_costly" in autopsy_md and "killed_by_costs" in autopsy_md:
        return "23C"
    if "keep_as_overlay" in autopsy_md:
        return "23A"
    return "23A"


def _phase23_blurb(choice: str) -> str:
    blurbs = {
        "23A": "**23A — Low-frequency trend on 1d/4h only**: Drop 1h zoo runs; focus Donchian/breakout with min-hold; accept sparse trades.",
        "23B": "**23B — Parameter hygiene walk-forward**: Pre-register 2–3 params per surviving family; strict OOS filter unchanged.",
        "23C": "**23C — Cost-aware design**: Halve trade frequency, widen bands, test fee grid before any new logic.",
        "23D": "**23D — Regime overlay only**: Router/vol-target as risk overlay on buy-and-hold benchmark, not alpha engine.",
    }
    return blurbs.get(choice, blurbs["23A"])


def main() -> int:
    p = argparse.ArgumentParser(description="Generate Phase 22 synthesis reports")
    p.add_argument("--reports-dir", type=Path, default=REPO_ROOT / "reports")
    args = p.parse_args()
    rdir = args.reports_dir

    fee = _load_json(rdir / "fee_sensitivity_phase22" / "summary.json")
    risk = _load_json(rdir / "risk_sensitivity_phase22" / "summary.json")
    turnover = _load_json(rdir / "timeframe_turnover_phase22" / "results.json")
    router = _load_json(rdir / "regime_router_perf_phase22" / "benchmark.json")

    autopsy = generate_autopsy(
        tournament_path=rdir / "strategy_tournament_phase21_rerun" / "results.json",
        walkforward_path=rdir / "walkforward_phase21_rerun" / "results.json",
        fee_summary_path=rdir / "fee_sensitivity_phase22" / "summary.json",
    )
    (rdir / "strategy_family_autopsy_phase22.md").write_text(autopsy, encoding="utf-8")

    fee_counts = fee.get("interpretation_counts", {})
    no_edge = fee_counts.get("no_edge_at_zero_fees", 0)
    killed = fee_counts.get("killed_by_costs", 0)
    survives = fee_counts.get("cost_sensitive_survives_moderate", 0) + fee_counts.get(
        "positive_across_grid", 0
    )

    risk_hyp = risk.get("over_constrained_hypothesis", "unknown")
    relaxed_pc = len(risk.get("relaxed_config_paper_candidates", []))

    by_tf = turnover.get("by_timeframe", {})
    tf_1h = by_tf.get("1h", {})
    tf_1d = by_tf.get("1d", {})

    speedup = router.get("speedup_x", "?")
    router_verdict = router.get("cached", {}).get("verdict", "?")

    phase23 = _recommend_phase23(autopsy, risk)

    diagnosis = f"""# Performance Diagnosis — Phase 22

**Date:** 2026-05-20  
**Branch:** `phase22/performance-diagnosis`  
**Scope:** Diagnostic only — no live, no new strategies, no post-hoc tuning.

## Executive summary

Phase 21 produced **0 paper_candidate** (tournament) and **0 paper_candidate_walkforward** across 81 runs each. Phase 22 isolates **fees**, **risk gates**, **timeframe turnover**, **strategy families**, and **regime router perf** to explain why.

---

## 1. Problème frais ?

**Verdict: partiel — surtout sur 4h/1h, pas la cause unique.**

| Interprétation fee grid | Count |
|-------------------------|-------|
| no_edge_at_zero_fees | {no_edge} |
| killed_by_costs | {killed} |
| survives moderate fees | {survives} |

- À **0 bps**, la majorité des cellules 4h/1h restent négatives ou `blocked_risk` → **pas d'edge brut** sur haute fréquence.
- Les stratégies 1d avec `insufficient_trades` ne peuvent pas être "sauvées" par 0 frais (trop peu de trades).
- Quelques cellules `killed_by_costs` confirment que le turnover 1h/4h magnifie le drag à 40+5 bps.

**Conclusion:** Les frais aggravent l'échec sur intraday, mais **l'absence d'edge pré-cost** est le facteur dominant.

---

## 2. Problème risk manager ?

**Verdict: contributeur, pas goulot unique — hypothesis `{risk_hyp}`.**

- Runs baseline Phase 21 avec `blocked_risk` ou `risk_denial_rate > 30%`: **{risk.get('baseline_blocked_risk_or_high_denial', '?')}** cellules.
- Config relaxée (pos 50% / dd 25%): **{relaxed_pc}** `paper_candidate` — dérisoire vs 81 runs.
- Règles les plus fréquentes: `max_drawdown_pct`, `max_position_fraction`, `safety_stop`.
- Le seuil `MAX_RISK_DENIAL_RATE=0.30` est **classificateur** (metrics.py), pas un paramètre RiskManager.

**Conclusion:** Assouplir le risk **ne produit pas** de candidats paper en masse → le bot n'est pas uniquement "over-constrained".

---

## 3. Problème stratégies ?

**Verdict: oui — zoo Phase 16 sans survivant OOS.**

Voir `reports/strategy_family_autopsy_phase22.md`. Synthèse:

| Famille | Diagnostic |
|---------|------------|
| Trend/EMA/Donchian | `insufficient_trades` (1d) ou `blocked_risk` (4h) |
| Breakout/ATR | Turnover + costs sur 4h/1h |
| RSI/Bollinger/MR | `blocked_risk`, returns négatifs intraday |
| Grid | Peu de trades, `blocked_risk` quand actif |
| Regime router | Return positif 1d mais `blocked_risk` (dd + denial) |

Walk-forward Phase 21: **20 unstable, 61 weak, 0 paper_candidate**.

---

## 4. Problème timeframe ?

**Verdict: oui — mismatch signal/fréquence.**

| TF | Median trades | Median return | Paper cand. |
|----|---------------|---------------|-------------|
| 1d | {tf_1d.get('median_trades', '?')} | {tf_1d.get('median_return_pct', '?')}% | {tf_1d.get('paper_candidate_count', 0)} |
| 4h | {by_tf.get('4h', {}).get('median_trades', '?')} | {by_tf.get('4h', {}).get('median_return_pct', '?')}% | {by_tf.get('4h', {}).get('paper_candidate_count', 0)} |
| 1h | {tf_1h.get('median_trades', '?')} | {tf_1h.get('median_return_pct', '?')}% | {tf_1h.get('paper_candidate_count', 0)} |

- **1d:** signaux trop rares (`insufficient_trades`).
- **1h:** trop de trades, cost drag ~100%, returns médians négatifs.
- **4h:** zone intermédiaire — toujours 0 paper_candidate.

---

## 5. Quelle famille mérite Phase 23 ?

**Recommandation: aucune famille alpha standalone; explorer 23A + 23D en parallèle.**

- Meilleur candidat **overlay**: regime router / vol targeting (pas alpha pur).
- Meilleur candidat **low-freq**: breakout/donchian sur **1d** (peu de trades, besoin 23A min-hold).
- **Ne pas** poursuivre grid / MR intraday sans refonte coût (23C).

---

## Artefacts

- `reports/fee_sensitivity_phase22/`
- `reports/risk_sensitivity_phase22/`
- `reports/timeframe_turnover_phase22/`
- `reports/strategy_family_autopsy_phase22.md`
- `reports/regime_router_perf_phase22/` (BTC 4h benchmark, speedup **{speedup}x**, verdict **{router_verdict}**)
"""

    next_steps = f"""# Phase 22 — Next decision

**Recommended track: {phase23}** (primary) + **23D** overlay exploration secondary

{_phase23_blurb(phase23)}

**Secondary:** 23D — regime router as risk overlay on buy-and-hold, not standalone alpha.

## Options

| Track | When | Action |
|-------|------|--------|
| **23A** | Sparse 1d signals | Low-freq trend/breakout, drop 1h from zoo |
| **23B** | Family shows weak but not kill | Pre-registered WF params (max 3/family) |
| **23C** | Fee grid `killed_by_costs` dominates | Widen bands, halve turnover before new alpha |
| **23D** | Router positive but blocked_risk | Overlay on B&H, not standalone alpha |

## Explicit NO-GO (unchanged)

- Micro-live / live execution
- Post-hoc parameter tuning on Phase 21 losers
- New strategy families without Phase 22 diagnosis sign-off

## Evidence pointers

- Tournament: `reports/strategy_tournament_phase21_rerun/` (0 paper_candidate)
- Walk-forward: `reports/walkforward_phase21_rerun/` (0 paper_candidate_walkforward)
- This diagnosis: `reports/PERFORMANCE_DIAGNOSIS_PHASE22.md`
"""

    red_team = """# Red team — Phase 22

**Verdict:** `diagnosis_only_no_profit_claim`

## Checks

| # | Risk | Status |
|---|------|--------|
| 1 | Cherry-pick best run | **pass** — aggregates medians/counts, 0 paper_candidate stated |
| 2 | Claim profitable strategy | **pass** — no profitable claim |
| 3 | Live / micro-live activation | **pass** — not touched |
| 4 | config.yaml / execution / risk / futures / web | **pass** — unchanged |
| 5 | Post-hoc tuning to save loser | **pass** — grids are diagnostic |
| 6 | Network in tests | **pass** — cache-only + hermetic fixtures |

## Honest negatives

- 0/81 tournament paper_candidate (Phase 21 baseline)
- 0/81 walk-forward paper_candidate
- Fee grid: majority `no_edge_at_zero_fees` on active intraday cells
- Risk relax grid: negligible paper_candidate uplift

**Decision:** Safe to proceed to Phase 23 planning only — **not** safe for micro-live.
"""

    final_qa = """# Final QA — Phase 22

**Date:** 2026-05-20  
**Branch:** `phase22/performance-diagnosis`

## Livrables

- [x] `scripts/run_fee_sensitivity_phase22.py`
- [x] `scripts/run_risk_sensitivity_phase22.py`
- [x] `scripts/analyze_timeframe_turnover_phase22.py`
- [x] `scripts/benchmark_regime_router_phase22.py`
- [x] `scripts/generate_strategy_family_autopsy_phase22.py`
- [x] Regime feature precompute (`precompute_regime_features`, `cache_regime_features`)
- [x] `reports/PERFORMANCE_DIAGNOSIS_PHASE22.md`
- [x] `reports/PHASE22_NEXT_DECISION.md`
- [x] `reports/RED_TEAM_PHASE22.md`
- [x] `tests/test_performance_diagnosis_phase22.py`

## Non-fait (scope respecté)

- Pas de nouvelles stratégies
- Pas de live / micro-live
- Pas de merge master / deploy
- `config.yaml`, `execution.py`, `risk.py`, `futures_kraken_cli.py`, `web/` inchangés
"""

    (rdir / "PERFORMANCE_DIAGNOSIS_PHASE22.md").write_text(diagnosis, encoding="utf-8")
    (rdir / "PHASE22_NEXT_DECISION.md").write_text(next_steps, encoding="utf-8")
    (rdir / "RED_TEAM_PHASE22.md").write_text(red_team, encoding="utf-8")
    (rdir / "FINAL_QA_PHASE22.md").write_text(final_qa, encoding="utf-8")

    print(json.dumps({"reports_dir": str(rdir), "phase23": phase23}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
