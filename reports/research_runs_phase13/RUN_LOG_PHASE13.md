# RUN_LOG Phase 13

**Date :** 2026-05-19  
**Branche :** `posthackathon/research-lab-phase-3-10`

## Commande canonique (cache-only)

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/event_study_volume_shock.py --run-all-variants --days 365 `
  --ohlc-source cache --use-cache-only --enable-holdout --holdout-fraction 0.5 `
  --embargo-days 7 --assets BTC,ETH,SOL `
  --output-dir reports/research_runs_phase13 --protocol protocol_a
```

**Exit code :** 2 (variantes blocked + SOL cache absent — attendu)

## Artifacts

| Fichier | Description |
|---------|-------------|
| `volume_shock_protocol_a_365d.json` | Run multi-actif + hold-out + provenance |
| `volume_shock_multi_asset_365d.json` | Copie canonique pour leaderboard |

## Données

- BTC/ETH : cache `ohlc_daily_{TICKER}.json` (371 bougies fenêtre 365j).  
- SOL : **blocked_data** — pas de cache local.

## Leaderboard

```powershell
python reports/_build_leaderboard.py --phase13
```

**OOS candidates :** 0
