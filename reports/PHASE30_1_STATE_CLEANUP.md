# Phase 30.1 — State cleanup

**Date :** 2026-05-21  
**Branche :** `phase30/observation-ops-ux`

## Problème

Les `state.json` des cibles Phase 28 portaient encore des métadonnées héritées du daemon Phase 19 :

| Champ | Legacy | Attendu |
|-------|--------|---------|
| asset | BTC | ETH |
| timeframe | 1d | 4h |
| strategy | regime_router | `trend_following+funding_basis` / `ema_crossover+funding_basis` |
| overlay | (absent) | funding_basis |

L'historique trades / decisions / equity **n'est pas touché**.

## Solution

- Module `src/bot/observation_state_migration.py`
- Migration automatique **en mémoire** au `load_state()` si legacy détecté
- Script `--dry-run` / `--apply` : `scripts/migrate_observation_state_phase30_1.py`
- `state_schema_version=1`, `migrated_from_legacy=true` si correction

## Commandes

```powershell
python scripts/migrate_observation_state_phase30_1.py --dry-run
python scripts/migrate_observation_state_phase30_1.py --apply
```

## Cibles

- `reports/paper_observation_phase28/trend_following_baseline/state.json`
- `reports/paper_observation_phase28/ema_crossover_baseline/state.json`
