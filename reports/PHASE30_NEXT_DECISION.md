# Phase 30 — Next decision

**Date :** 2026-05-21  
**Branche :** `phase30/vps-observation-cron`

## Décision

### **`ready_for_vps_cron`**

| Gate | Status |
|------|--------|
| Scripts ops bash + PowerShell | OK |
| Garde-fous `observation_ops_guards.py` | OK |
| Tests Phase 30 | OK |
| QA locale once (PowerShell) | OK |
| STOP_OBSERVATION absent | OK |
| Fichiers sensibles unchanged | OK |
| Micro-live | **NO-GO** |
| Loop infinie PC | **Non lancée** (cron 4h VPS à la place) |

## Contexte

Phase 29 a validé `continue_observation`. Phase 30 prépare l'exécution **cron 4h sur VPS** avec refresh caches publics **avant** le daemon once — pas de loop infinie locale.

## Prochaines actions (utilisateur)

1. SSH VPS demain — checkout branche, activer venv
2. Installer cron `0 */4 * * *` (voir `PHASE30_VPS_CRON_SETUP.md`)
3. Vérifier premier log dans `ops_logs/`
4. J+7 / J+14 → `PHASE31_REVIEW_CHECKLIST.md`

## Options explicites (non retenues)

| Option | Raison |
|--------|--------|
| `fix_required` | Non — QA locale PASS |
| `kill_overlay` | Non — STOP absent |
| Loop PC 14j | Remplacée par cron VPS 4h |
| `micro_live_review` | **Interdit** — voir `MICRO_LIVE_GO_NO_GO_PHASE30.md` |

## Commande once locale (référence)

```powershell
powershell -File scripts/ops_run_observation_once_phase30.ps1
```

## Cron VPS (référence)

```cron
0 */4 * * * KRAKEN_ALPHA_ROOT=/root/kraken-alpha-agent /bin/bash /root/kraken-alpha-agent/scripts/ops_run_observation_once_phase30.sh >> /root/kraken-alpha-agent/reports/paper_observation_phase28/ops_logs/cron_stdout.log 2>&1
```
