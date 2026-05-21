# Phase 29 — Observation sanity check

**Date :** 2026-05-21  
**Branche :** `phase29/observation-ops`

## Commandes exécutées

```powershell
git checkout phase29/observation-ops
git status
python scripts/run_overlay_observation_daemon_phase28.py --run-all-targets --mode once --cache-only
python scripts/generate_overlay_observation_report_phase28.py --all-targets
python scripts/generate_overlay_observation_report_phase28.py --weekly --all-targets
python scripts/aggregate_observation_metrics_phase29.py
```

## Résultat daemon (`--mode once --cache-only`)

| Cible | Status | Note |
|-------|--------|------|
| trend_following_baseline | `skipped` | `duplicate_candle` — état déjà à jour (attendu) |
| ema_crossover_baseline | `skipped` | `duplicate_candle` — état déjà à jour (attendu) |

Le skip duplicate confirme la persistance `last_processed_timestamp` et l'idempotence Phase 28.

## Fichiers requis — existence

| Fichier | trend_following | ema_crossover |
|---------|-----------------|---------------|
| `state.json` | OK | OK |
| `decisions.jsonl` | OK (1 row) | OK (1 row) |
| `shadow_comparison.jsonl` | OK (1 row) | OK (1 row) |
| `equity_curve.csv` | OK | OK |
| `trades.csv` | OK (114 trades replay) | OK (100 trades replay) |
| `positions.json` | OK | OK |

## STOP_OBSERVATION

**Absent** — `reports/paper_observation_phase28/STOP_OBSERVATION` n'existe pas.

## Rapports générés

- Weekly rollup : `reports/paper_observation_phase28/weekly_summary_2026-W21.md`
- Monitoring Phase 29 : `reports/PHASE29_OBSERVATION_MONITORING.md`
- Metrics JSON : `reports/phase29_observation_metrics/summary.json`

## Snapshot métriques (T0 observation)

| Métrique | trend_following | ema_crossover |
|----------|-----------------|---------------|
| Equity overlay | 1112.09 USD | 965.88 USD |
| Decisions | 1 | 1 |
| Block rate | 0% | 0% |
| Kill triggered | non | non |
| observation_only | true | true |

## Verdict sanity

**PASS** — pipeline observation opérationnel, état persisté, pas de flag STOP, pas d'ordre live.

## Notes

- `state.json` contient des champs legacy (`asset=BTC`, `strategy=regime_router`) hérités d'un run antérieur ; les décisions/shadow récents montrent bien ETH 4h overlay (`price=2129.84`, `observation_only=true`). À surveiller lors des prochains cycles loop (le moteur réécrit `strategy` au premier run complet).
- Fenêtre forward encore **T0** (1 barre shadow/decision) — normal avant loop 14j.
