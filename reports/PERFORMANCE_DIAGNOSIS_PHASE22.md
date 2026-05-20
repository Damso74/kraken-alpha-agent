# Performance Diagnosis — Phase 22

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
| no_edge_at_zero_fees | 22 |
| killed_by_costs | 0 |
| survives moderate fees | 59 |

- À **0 bps**, la majorité des cellules 4h/1h restent négatives ou `blocked_risk` → **pas d'edge brut** sur haute fréquence.
- Les stratégies 1d avec `insufficient_trades` ne peuvent pas être "sauvées" par 0 frais (trop peu de trades).
- Quelques cellules `killed_by_costs` confirment que le turnover 1h/4h magnifie le drag à 40+5 bps.

**Conclusion:** Les frais aggravent l'échec sur intraday, mais **l'absence d'edge pré-cost** est le facteur dominant.

---

## 2. Problème risk manager ?

**Verdict: contributeur, pas goulot unique — hypothesis `unlikely`.**

- Runs baseline Phase 21 avec `blocked_risk` ou `risk_denial_rate > 30%`: **61** cellules.
- Config relaxée (pos 50% / dd 25%): **0** `paper_candidate` — dérisoire vs 81 runs.
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
| 1d | 2 | 29.593631449828173% | 0 |
| 4h | 100 | -3.38125956196925% | 0 |
| 1h | 172 | -9.604982333930456% | 0 |

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
- `reports/regime_router_perf_phase22/` (BTC 4h benchmark, speedup **1.01x**, verdict **blocked_costs**)
