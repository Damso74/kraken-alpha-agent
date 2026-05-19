# Research Decision Board — kraken-alpha-agent

**Date (UTC) :** 2026-05-19  
**Agent :** 26 — Tableau de décision unifié  
**Sources :** QA phases 4–10, leaderboard V2, comparaison Phase 3/6, réalisme économique, robustesse régime, concentration, backlog Phase 9, top 5 Phase 11

---

## Résumé exécutif

| Métrique | Valeur |
|----------|--------|
| Hypothèses dans le board | **18** |
| Exécutées Phase 6 | **6** |
| Planifiées Phase 11 | **5** |
| `candidate_for_oos_testing` | **0** (attendu) |
| `blocked_data` | **3** (0 events ou cache absent) |
| `weak_evidence` | **3** |
| `archive` / `kill` | **5** |
| Signaux tradables / live-ready | **0** |

**Règles appliquées :** aucune claim live-ready, tradable ou profitable ; 0 événements → `blocked_data` (≠ `weak_evidence`) ; blocked ≠ weak ; OOS = 0 candidat.

**Référence autoritaire :** `reports/ALPHA_RESEARCH_LEADERBOARD_V2.json` (Phase 3 `stablecoins_365d.json` obsolète si `weak evidence` avec 0 events).

---

## Légende des classifications

| Classification | Signification |
|----------------|---------------|
| `kill` | No-go ou rejet méthodologique ; ne pas réallouer |
| `blocked_data` | Données manquantes ou 0 events — pas de conclusion stats |
| `weak_evidence` | Run OK ; BH / placebo / économie insuffisants |
| `retry_with_fixed_data` | Ré-run après seed cache ou collector |
| `retry_with_pre_registered_threshold` | Seuil gelé **avant** run principal |
| `candidate_for_oos_testing` | Seul statut OOS — **aucun actuellement** |
| `archive` | Test négatif stable ; garder artefact |
| `design_only` | Spécifié ; pas encore exécuté |

---

## Tableau de décision unifié

| hypothesis_id | signal | status | data status | events | BH rej | placebo | economic verdict | regime verdict | concentration verdict | classification | next action | owner | priority |
|---------------|--------|--------|-------------|--------|--------|---------|------------------|----------------|----------------------|----------------|-------------|-------|----------|
| P9-CA-031 | `calendar_weekend_start` | exécuté P6 | ok | 105 | 0/5 | bootstrap 200 — indistinguable | economically impossible (gross 0,39%) | single_regime | not_assessed | **archive** | Archiver ; pas de variantes week-end | research | 25 |
| P9-SC-001 | `stablecoin_supply_z_high` | exécuté P6 | ok ; **0 events** z≥1,5 | **0** | 0/0 | non exécuté | reject puissance | blocked | not_assessed | **blocked_data** | Voir P9-SC-001-PR | data | 74 |
| P9-AT-011 | `wikipedia_btc_attention` | exécuté P6 | ok (UA fixé) | 16 | 0/5 | bootstrap 200 | economically impossible (−0,96%) | not_assessed | not_assessed | **weak_evidence** | Pas re-prioriser BTC | research | 78 |
| P9-EX-001 | `exchange_status_major_incident` | exécuté P6 | ok | 2 | 0/5 | bootstrap 200 | economically impossible (n<5) | insufficient_data | insufficient_evidence | **weak_evidence** | Fenêtre 730j ou fusion venues | data | 45 |
| P9-AT-017 | `demo_fear_greed_extreme_fear` | exécuté P6 demo | ok | 129 | 2/5 vol | bootstrap 200 | economically impossible ; turnover 34,9% | pending | not_assessed | **weak_evidence** | Harness multi-actifs requis | research | 68 |
| P9-OC-041 | `eth_gas_congestion` | bloqué P6 | **cache absent** | — | — | non exécuté | non évalué | blocked | — | **blocked_data** | Seed ≥181 rows gas history | data | 76 |
| P9-SC-001-PR | `stablecoin_supply_z_high` | plan P11 | ok | — | — | bootstrap prévu | non évalué | — | — | **retry_with_pre_registered_threshold** | z=1,0 gelé + run dédié | research | 74 |
| P9-CA-032 | `calendar_us_open` | plan P11 | ready | — | — | bootstrap + placebo cal | non évalué | — | — | **design_only** | `event_study_calendar --calendar-flag us_open` | research | 72 |
| P9-CA-037 | `calendar_third_friday_expiry` | plan P11 | ready | — | — | bootstrap 200 | non évalué | — | — | **design_only** | `event_study_deribit_expiry --days 730` | research | 64 |
| P9-MS-023 | `volume_spike_z_high` | plan P11 | ready | — | — | bootstrap ; turnover ≤30% | non évalué | — | — | **design_only** | Nouveau signal + script | implementation | 63 |
| P9-OC-041-R | `eth_gas_congestion` | plan P11 retry | blocked until seed | — | — | bootstrap prévu | non évalué | — | — | **retry_with_fixed_data** | Run post-seed eth_gas_365d.json | data + research | 76 |
| P9-AT-012 | `wikipedia_eth_attention` | backlog | ready | — | — | — | non évalué | — | — | **archive** | Reporter (doublon AT-011) | research | 62 |
| P9-MS-021 | `realized_vol_weekend` | backlog | ready | — | — | — | non évalué | — | — | **kill** | Famille week-end rejetée | research | 70 |
| P9-XS-076 | `xstocks_spot_arb` | frozen | API Permission denied | — | — | — | n/a | n/a | n/a | **kill** | No-go PEDSL-CY | governance | 5 |
| P9-XS-077 | `xstocks_perp_funding` | frozen | wouldNotReducePosition | — | — | — | n/a | n/a | n/a | **kill** | No-go PEDSL-CY | governance | 5 |
| P9-OC-048 | `eth_chain_tvl_z_high` | backlog | partial | — | — | — | non évalué | — | — | **design_only** | Phase 12 | implementation | 61 |
| P9-OC-042 | `btc_mempool_vsize_z_high` | backlog | **collector manquant** | — | — | — | non évalué | — | — | **blocked_data** | Créer collector Mempool.space | data | 66 |
| P9-LG-093 | `dark_web_volume` | legal no-go | interdit | — | — | — | n/a | n/a | n/a | **kill** | Compliance | governance | 0 |

---

## Synthèse par couche de rejet

### G0 — Puissance / data

- **blocked_data :** P9-SC-001 (0 events), P9-OC-041 (cache), P9-OC-042 (collector)
- Règle : **0 events ≠ weak_evidence**

### G1 — Inférence (BH-FDR α=0,05)

- Aucune hypothèse exécutée ne survit BH sur retour post_7
- Demo F&G : 2/5 sur vol uniquement → **non promu** (harness demo)

### G2 — Régime & concentration

- Module livré (`regime_analysis.py`, `concentration.py`) ; **matrice non remplie** sauf CA-031 (`single_regime`)
- Tous les signaux exécutés : `concentration_verdict = not_assessed` ou `insufficient_evidence`

### G3 — Réalisme économique

- Round-trip pessimiste major : **1,00 %** ; seuil brut suspect : **0,50 %**
- **5/5** signaux évalués économiquement → rejet (`economically impossible` ou puissance)

### G4 — OOS

- **`oos_candidate_count: 0`** — conforme politique anti-curve-fit

---

## Décisions clés Phase 6 → Phase 11

| Transition | Avant (P3) | Après (P6/V2) | Décision board |
|------------|------------|---------------|----------------|
| Stablecoins z≥1,5 | weak evidence (bug) | **blocked_data** | Retry via P9-SC-001-PR seulement |
| Wikipedia BTC | blocked 403 | weak_evidence | Archive ; pas Phase 11 top 5 |
| Weekend UTC | not supported | archive | Kill variantes MS-021 |
| ETH gas | blocked | blocked_data | Sprint 3 seed parallèle |

---

## TOP 3 prochains sprints (MAX)

### 1. Sprint calendrier Phase 11

**Hypothèses :** P9-CA-032, P9-CA-037  
**Effort :** S (1–1,5 j)  
**Livrables :**

- `reports/research_runs_v2/calendar_us_open_730d.json`
- `reports/research_runs_v2/deribit_expiry_730d.json`
- Entrées `RUN_LOG_V2.md` + `python reports/_build_leaderboard.py --v2`

**Pourquoi en premier :** infra prête, zéro API externe, contrôle nullité méthodologique avant hypothèses data-heavy.

---

### 2. Sprint stablecoins pré-enregistré

**Hypothèse :** P9-SC-001-PR  
**Effort :** S (0,5 j)  
**Livrables :**

- Ligne pré-enregistrement (z=1,0, lookback=180, date gel) dans RUN_LOG
- `reports/research_runs_v2/stablecoins_z10_365d.json`
- Classification attendue : `weak_evidence` ou `not supported` — **pas OOS**

**Pourquoi :** sortir P9-SC-001 du `blocked_data` z≥1,5 avec protocole honnête (probe z=1,0 = 12 events exploratoires uniquement).

---

### 3. Sprint microstructure + seed gas (parallèle)

**Hypothèses :** P9-MS-023, P9-OC-041-R  
**Effort :** M (3–4 j)  
**Livrables :**

- `src/signals/ohlc_volume_spike.py`, `scripts/event_study_volume_spike.py`, tests
- `data/collector_cache/etherscan_gas_history.json` (≥181 rows)
- `reports/research_runs_v2/volume_spike_365d.json`
- `reports/research_runs_v2/eth_gas_365d.json` (si seed OK)

**Pourquoi :** seul lot Phase 11 avec code neuf ; seed gas débloque P9-OC-041 sans bloquer sprints 1–2.

---

## Ce qu'on ne fait pas

- Promouvoir un signal vers `config.yaml` ou profil live
- Labelliser tradable / profitable / live-ready
- Relancer stablecoins z≥1,5 sans pré-enregistrement
- Réutiliser artefact Phase 3 `stablecoins_365d.json` (verdict obsolète)
- Investir dans familles week-end (CA-031, MS-021) ou xStocks live PEDSL-CY

---

## Références

- [`ALPHA_RESEARCH_LEADERBOARD_V2.json`](ALPHA_RESEARCH_LEADERBOARD_V2.json)
- [`FINAL_QA_PHASE_4_10.md`](FINAL_QA_PHASE_4_10.md)
- [`PHASE_3_VS_PHASE_6.md`](PHASE_3_VS_PHASE_6.md)
- [`ECONOMIC_REALISM.md`](ECONOMIC_REALISM.md)
- [`REGIME_ROBUSTNESS.md`](REGIME_ROBUSTNESS.md)
- [`CONCENTRATION_RISK.md`](CONCENTRATION_RISK.md)
- [`../docs/NEXT_5_HYPOTHESES.md`](../docs/NEXT_5_HYPOTHESES.md)
- [`../docs/HYPOTHESIS_BACKLOG_PHASE_9.md`](../docs/HYPOTHESIS_BACKLOG_PHASE_9.md)
- Machine-readable : [`RESEARCH_DECISION_BOARD.json`](RESEARCH_DECISION_BOARD.json)

---

*Généré par l’agent 26 — Research decision board. Recherche read-only uniquement.*
