# Phase 30 — VPS cron setup (observation 4h)

**Date :** 2026-05-21  
**Branche :** `phase30/vps-observation-cron`  
**Décision :** **`ready_for_vps_cron`**

> Observation-only. Aucun ordre live. Pas de triple opt-in.

## Objectif

Exécuter toutes les **4 heures** sur le VPS (ou manuellement en local) :

1. Refresh optionnel des caches publics ETH (OHLC 4h, funding, basis)
2. Daemon overlay paper **once** (2 cibles, cache-only)
3. Rapports + agrégation métriques
4. Log horodaté + garde-fous STOP / legacy state

## Prérequis VPS

| Item | Détail |
|------|--------|
| OS | Ubuntu 24.04 LTS (Vultr `ewr`) |
| Repo | `/root/kraken-alpha-agent` |
| Branche | `phase30/vps-observation-cron` (depuis `phase29/observation-ops`) |
| venv | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| Caches initiaux | `data/collector_cache/` peuplé (ETH 4h OHLC + derivatives) |
| STOP flag | **absent** : `reports/paper_observation_phase28/STOP_OBSERVATION` |
| Réseau | Sortant HTTPS (Binance public pour refresh caches) |
| **Interdit** | Live keys session, `TRADING_MODE=live`, loop infinie sans `--allow-infinite-loop` |

### Bootstrap caches (une fois)

```bash
cd /root/kraken-alpha-agent
source .venv/bin/activate
python scripts/build_intraday_cache.py --assets ETH --timeframes 4h
python scripts/build_derivatives_cache_phase26.py --assets ETH
python scripts/build_basis_cache_phase27.py --assets ETH
```

> Le refresh OHLC complet peut être lent (pagination Binance). Le script ops le tente à chaque run mais **continue** si échec réseau.

## Script ops

| Plateforme | Chemin |
|------------|--------|
| VPS Linux | `scripts/ops_run_observation_once_phase30.sh` |
| Windows local | `scripts/ops_run_observation_once_phase30.ps1` |

Variable optionnelle : `KRAKEN_ALPHA_ROOT=/chemin/vers/repo`

## Cron VPS (toutes les 4h)

Éditer crontab root :

```bash
crontab -e
```

Exemple (démarrage à minute 0, toutes les 4h UTC) :

```cron
0 */4 * * * KRAKEN_ALPHA_ROOT=/root/kraken-alpha-agent /bin/bash /root/kraken-alpha-agent/scripts/ops_run_observation_once_phase30.sh >> /root/kraken-alpha-agent/reports/paper_observation_phase28/ops_logs/cron_stdout.log 2>&1
```

Chaque run produit aussi un log dédié :

`reports/paper_observation_phase28/ops_logs/YYYYMMDD_HHMMSS.log`

## Commande manuelle once

### Bash (VPS / WSL)

```bash
cd /root/kraken-alpha-agent
source .venv/bin/activate
bash scripts/ops_run_observation_once_phase30.sh
```

### PowerShell (Windows local)

```powershell
cd c:\Users\credo\Documents\Code_Informatique\Projets-en-cours\kraken-alpha-agent
.\.venv\Scripts\Activate.ps1
powershell -File scripts/ops_run_observation_once_phase30.ps1
```

## Procédure STOP

Arrêt propre sans supprimer l'état paper :

```bash
touch /root/kraken-alpha-agent/reports/paper_observation_phase28/STOP_OBSERVATION
```

Le script ops détecte le flag, **skip le daemon**, exit 0.

**Ne pas** supprimer `STOP_OBSERVATION` sans revue humaine (voir `KILL_CRITERIA.md`).

## Rapports quotidiens (hors cron 4h)

Optionnel — rollup hebdo ou snapshot manuel :

```bash
python scripts/generate_overlay_observation_report_phase28.py --all-targets
python scripts/generate_overlay_observation_report_phase28.py --weekly --all-targets
python scripts/aggregate_observation_metrics_phase29.py
```

## Revues J+7 / J+14

Checklist : [`reports/PHASE31_REVIEW_CHECKLIST.md`](PHASE31_REVIEW_CHECKLIST.md)

| Jour | Action |
|------|--------|
| J+7 | Remplir checklist 7j, lire `summary.json` |
| J+14 | Remplir checklist 14j → décision Phase 31 |

## Fichiers à surveiller

| Fichier | Rôle |
|---------|------|
| `reports/phase29_observation_metrics/summary.json` | Métriques agrégées (source de vérité) |
| `reports/PHASE29_OBSERVATION_MONITORING.md` | Markdown monitoring auto-généré |
| `reports/paper_observation_phase28/STOP_OBSERVATION` | Kill manuel — stop immédiat |
| `reports/paper_observation_phase28/ops_logs/*.log` | Logs ops horodatés |
| `reports/paper_observation_phase28/*/state.json` | État daemon par cible |
| `reports/paper_observation_phase28/*/decisions.jsonl` | Décisions overlay |
| `reports/paper_observation_phase28/*/shadow_comparison.jsonl` | Shadow compare |

## Calendrier refresh caches (suggestion)

| Feed | Fréquence | Script |
|------|-----------|--------|
| OHLC ETH 4h | **1×/jour** (00:15 UTC) | `build_intraday_cache.py --assets ETH --timeframes 4h` |
| Funding | **every 4h** (inclus dans ops script) | `build_derivatives_cache_phase26.py --assets ETH` |
| Basis | **every 4h** (inclus dans ops script) | `build_basis_cache_phase27.py --assets ETH` |

Le script ops Phase 30 tente les trois à chaque run ; seuls les échecs refresh sont non-fatals.

## Garde-fous module

`src/bot/observation_ops_guards.py` :

- `should_skip_observation()` — flag STOP
- `check_state_legacy_warning()` — détecte `asset=BTC`, `strategy=regime_router`, `timeframe=1d`

## Décision Phase 30

**`ready_for_vps_cron`** — scripts ops testés localement, pytest green, fichiers sensibles inchangés. Déploiement cron VPS = action utilisateur (demain).

## Interdictions (rappel)

- Pas live / micro-live / triple opt-in
- Pas de modification `execution.py`, `risk.py`, `futures_kraken_cli.py`, `config.yaml`, `web/`
- Pas de tuning overlay
- Pas de merge master automatique
