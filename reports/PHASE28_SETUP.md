# Phase 28 — Setup commands

PowerShell, depuis la racine du repo :

```powershell
git checkout phase28/eth4h-overlay-paper-observation
.\.venv\Scripts\Activate.ps1
```

## Prérequis cache (lecture seule, pas de réseau en prod daemon)

Vérifier présence :
- `data/collector_cache/ohlc_4h_ETH.json`
- `data/collector_cache/funding_ETH.json`
- `data/collector_cache/basis_ETH_4h.json`

Rebuild si stale (optionnel, hors daemon) :
```powershell
python scripts/build_derivatives_cache_phase26.py --assets ETH
python scripts/build_basis_cache_phase27.py --assets ETH --timeframes 4h
```

## Cycle unique (test / cron manuel)

```powershell
# Les deux cibles Phase 28
python scripts/run_overlay_observation_daemon_phase28.py --run-all-targets --mode once --cache-only

# Une cible
python scripts/run_overlay_observation_daemon_phase28.py `
  --asset ETH --timeframe 4h `
  --strategy trend_following --variant baseline --overlay funding_basis `
  --mode once --cache-only
```

## Observation 2–4 semaines (loop)

```powershell
# Toutes les 4h (aligné bougie), boucle infinie — Ctrl+C pour arrêter
python scripts/run_overlay_observation_daemon_phase28.py `
  --run-all-targets `
  --mode loop `
  --interval-seconds 14400 `
  --allow-infinite-loop `
  --cache-only
```

Alternative cron Windows (toutes les 4h, once) :
```powershell
python scripts/run_overlay_observation_daemon_phase28.py --run-all-targets --mode once --cache-only
```

## Rapports

```powershell
# Daily (par stratégie)
python scripts/generate_overlay_observation_report_phase28.py `
  --state-dir reports/paper_observation_phase28/trend_following_baseline

# Weekly rollup (les 2 cibles)
python scripts/generate_overlay_observation_report_phase28.py --weekly --all-targets
```

## Arrêt d'urgence

```powershell
New-Item -ItemType File -Path reports/paper_observation_phase28/STOP_OBSERVATION -Force
```

Voir `reports/paper_observation_phase28/KILL_CRITERIA.md` pour critères automatiques.

## Interdit

- Pas de `--allow-live`, pas de `run_agent_loop.py`
- Ne pas modifier `execution.py`, `risk.py`, `futures_kraken_cli.py`, `config.yaml`, `web/`
