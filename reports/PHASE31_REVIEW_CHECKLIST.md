# Phase 31 — Review checklist (7j / 14j)

**Usage :** remplir après 7 et 14 jours de loop Phase 30. Source de vérité : `reports/phase29_observation_metrics/summary.json`.

## Commande review

```powershell
python scripts/aggregate_observation_metrics_phase29.py
# Lire reports/PHASE29_OBSERVATION_MONITORING.md
# Lire reports/phase29_observation_metrics/summary.json
```

---

## Checklist 7 jours (~42 barres 4h)

| # | Item | Seuil | trend_following | ema_crossover | PASS? |
|---|------|-------|-----------------|---------------|-------|
| 1 | STOP_OBSERVATION absent | oui | | | |
| 2 | observation_only | true | | | |
| 3 | Shadow rows | ≥ 7 | | | |
| 4 | Decision count | ≥ 7 | | | |
| 5 | Block rate (30 barres) | ≤ 60% | | | |
| 6 | Stale data count | 0 persistant | | | |
| 7 | Error count | 0 nouveau | | | |
| 8 | Kill should_kill | false | | | |
| 9 | Incoherent blocks | < 3 | | | |
| 10 | Overlay equity vs 1k | documenté | | | |

**Décision 7j :** continue_observation | fix_required | kill_overlay

**Notes :**

---

## Checklist 14 jours (~84 barres 4h)

| # | Item | Seuil | trend_following | ema_crossover | PASS? |
|---|------|-------|-----------------|---------------|-------|
| 1 | Shadow rows | ≥ 30 | | | |
| 2 | Trade count | ≥ 5 | | | |
| 3 | Block rate rolling | ≤ 60% | | | |
| 4 | Missed upside proxy | documenté | | | |
| 5 | Avoided drawdown proxy | documenté | | | |
| 6 | Equity gap vs standalone | ≥ −5 pp | n/a persisted | n/a | |
| 7 | Max drawdown overlay | documenté | | | |
| 8 | B&H return proxy | comparé | | | |
| 9 | Kill criteria | 0 trigger cumulé | | | |
| 10 | Micro-live review | **INTERDIT** | — | — | NO-GO |

### Ratio interprétation shadow (14j)

| Signal | Interprétation continue | Interprétation kill |
|--------|-------------------------|---------------------|
| missed_upside >> avoided_drawdown | overlay trop défensif | kill_overlay |
| avoided_drawdown >> missed_upside | overlay utile | continue |
| block rate > 60% | stratégie neutralisée | kill_overlay |
| trades < 5 | sample insuffisant | fix cache ou kill |

**Décision 14j :** continue_observation | extend_observation | kill_overlay | fix_required

**Micro-live :** toujours NO-GO (PEDSL-CY + <28j recommandé)

**Notes :**

---

## Agrégation multi-semaine (28j — preview)

Pour Phase 31+ étendue, comparer deux snapshots `summary.json` :

```powershell
# Semaine 1 baseline
Copy-Item reports/phase29_observation_metrics/summary.json reports/phase29_observation_metrics/summary_W1.json
# Semaine 4
python scripts/aggregate_observation_metrics_phase29.py
```

Diff manuelle : `decision_count`, `block_rate_on_signals`, `shadow_proxies`, `kill_criteria`.

## Références

- Kill : `reports/paper_observation_phase28/KILL_CRITERIA.md`
- Playbook loop : `reports/PHASE30_OBSERVATION_PLAYBOOK.md`
- Décision Phase 29 : `reports/PHASE29_NEXT_DECISION.md`
