# Phase 30.4 — VPS healthcheck + cron supervisor

**Date :** 2026-05-21  
**Branche :** `phase30/observation-ops-ux`

## Objectif

Superviser l’observation forward paper sans toucher au moteur de trading :

- Healthcheck JSON/MD (`healthcheck.json`, `HEALTHCHECK.md`)
- Digest ops dry-run (`ops_digest.json`, `OPS_DIGEST.md`)
- Install / uninstall cron VPS (`install_observation_cron_phase30.sh`)
- Intégration fail-soft dans `ops_run_observation_once_phase30.sh` / `.ps1`

## Modules

| Fichier | Rôle |
|---------|------|
| `src/bot/observation_healthcheck.py` | Règles pass/warning/fail |
| `src/bot/observation_ops_digest.py` | `next_action` opérateur |
| `scripts/check_observation_health_phase30.py` | CLI healthcheck |
| `scripts/generate_observation_ops_digest_phase30.py` | CLI digest |
| `scripts/install_observation_cron_phase30.sh` | Crontab 4h (sans doublon) |
| `scripts/uninstall_observation_cron_phase30.sh` | Retrait crontab |

## Règles healthcheck (résumé)

**FAIL :** STOP actif, `critical_count>0`, asset≠ETH / TF≠4h, `observation_only` false, dashboard/summary absents, pas de log ops si cron actif, log >6h si cron actif.

**WARNING :** `warning_count>0`, stale data, log 4–6h, dashboard vieux, décisions bloquées 8h+.

**PASS :** nominal ETH 4h, pas de STOP, pas de critical.

## Notifications

Dry-run uniquement : aucun email/webhook ; lire `OPS_DIGEST.md` et `next_action` dans `ops_digest.json`.

## Commandes

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/check_observation_health_phase30.py --exit-code
python scripts/generate_observation_ops_digest_phase30.py
```

VPS :

```bash
bash scripts/install_observation_cron_phase30.sh
# ou
bash scripts/uninstall_observation_cron_phase30.sh
```

## Interdictions

- Pas de live / micro-live / Kraken API
- Pas de modification `execution.py`, `risk.py`, `futures_kraken_cli.py`, `config.yaml`, `web/`
- Pas de merge `master`
