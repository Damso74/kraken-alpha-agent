# Final QA — Phase 12

**Date :** 2026-05-19  
**Branche :** `posthackathon/research-lab-phase-3-10`

## Critères de succès

| Critère | Attendu | Résultat |
|---------|---------|----------|
| Tests pytest | ≥ 622 pass | **639 pass** (17 nouveaux) |
| `config.yaml` diff | vide | **OK** |
| Candidats OOS Phase 12 | 0 | **0** (`ALPHA_RESEARCH_LEADERBOARD_PHASE12.json`) |
| Signaux tradables | 0 | **0** |
| Réseau dans tests | non | **OK** (tests unitaires cache tmp) |
| `research_runs_phase12/` | données réelles / reprise honnête | **OK** (voir RUN_LOG) |

## Workstreams livrés

| WS | Livrable | Statut |
|----|----------|--------|
| WS0 | `PHASE12_BASELINE.md` | OK |
| WS1 | `red_team_verdicts.json`, gating leaderboard, docs red team | OK |
| WS2 | `holdout.py`, `--enable-holdout`, `G4_HOLDOUT.md`, tests OOS | OK |
| WS3 | `signal_registry.json`, `signal_registry.py`, docs | OK |
| WS4 | `_provenance.py`, intégration `_event_study_common` | OK |
| WS5a | Alias calendrier Sunday/Monday | OK |
| WS5b | Placebos volume sur `post_7` | OK |
| WS5c | Bootstrap `random_timestamps` exchange | OK |
| WS5d | Hold-out Wikipedia | OK |
| WS6 | `research_runs_phase12/`, RUN_LOG, leaderboard `--phase12` | OK |
| WS7 | Ce document + pytest complet | OK |

## Blockers résiduels

1. **Cache Wikimedia panier crypto** : une seule entrée dans `wikimedia.json` locale — le re-test Wikipedia Phase 12 réutilise l’artefact Phase 11 + hold-out sur OHLC cache (documenté dans `RUN_LOG_PHASE12.md`). Pas de fetch réseau en CI.
2. **Stablecoins / exchange / calendrier** : non re-run Phase 12 (hors scope WS6 : volume + Wikipedia uniquement).

## Verdict QA

**PASS** — sprint méthodologie : gates plus stricts, **0 promotion OOS**, suite de tests verte, `config.yaml` intact.
