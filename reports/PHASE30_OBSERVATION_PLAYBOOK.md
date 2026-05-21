# Phase 30 — Observation playbook (14 jours)

**Objectif :** accumuler ≥84 barres 4h shadow/decisions sur les 2 cibles ETH overlay sans live.

> **Ne pas lancer depuis l'agent** — trop long pour une session. L'utilisateur exécute localement ou sur VPS (cache-only).

## Prérequis

- Branche `phase29/observation-ops` (ou descendant)
- Cache ETH 4h + funding + basis dans `data/collector_cache/`
- `STOP_OBSERVATION` absent
- venv activé

## Jour 0 — baseline

```powershell
cd c:\Users\credo\Documents\Code_Informatique\Projets-en-cours\kraken-alpha-agent
.\.venv\Scripts\Activate.ps1

python scripts/run_overlay_observation_daemon_phase28.py --run-all-targets --mode once --cache-only
python scripts/aggregate_observation_metrics_phase29.py
```

Archiver `reports/phase29_observation_metrics/summary.json` → copie datée si souhaité.

## Jours 1–14 — loop daemon

```powershell
python scripts/run_overlay_observation_daemon_phase28.py `
  --run-all-targets `
  --mode loop `
  --interval-seconds 14400 `
  --allow-infinite-loop `
  --cache-only
```

- Interval 14400 s = 4h (aligné timeframe)
- Chaque cycle : 2 cibles séquentielles, lock par state dir
- Arrêt : `Ctrl+C`

### Refresh cache (optionnel, hebdo)

Si collector tourné séparément, rebuild caches derivatives avant le cycle du lundi. **Pas de tuning overlay.**

## Daily cron (Task Scheduler Windows)

Programmer à 00:15 UTC (après clôture 4h) :

```powershell
cd c:\Users\credo\Documents\Code_Informatique\Projets-en-cours\kraken-alpha-agent
.\.venv\Scripts\Activate.ps1
python scripts/generate_overlay_observation_report_phase28.py --all-targets
python scripts/aggregate_observation_metrics_phase29.py
```

Logs : stdout → fichier `reports/phase30_observation_metrics/daily_YYYY-MM-DD.log`

## Weekly cron (lundi 08:00 UTC)

```powershell
python scripts/generate_overlay_observation_report_phase28.py --weekly --all-targets
python scripts/aggregate_observation_metrics_phase29.py
```

Copier le template hebdo :

```powershell
Copy-Item reports/templates/OBSERVATION_WEEKLY_TEMPLATE.md `
  reports/paper_observation_phase28/weekly_review_YYYY-Www.md
```

Remplir manuellement ou via diff vs `summary.json` précédent.

## Monitoring checkpoints

| Jour | Action |
|------|--------|
| 1 | Vérifier shadow rows > 1, pas de STOP |
| 3 | `aggregate_observation_metrics_phase29.py` — block rate |
| 7 | Review Phase 31 checklist 7j |
| 14 | Review Phase 31 checklist 14j → décision Phase 31 |

## Si STOP_OBSERVATION apparaît

1. Lire le fichier (raisons kill)
2. **Ne pas** supprimer sans analyse
3. Décision → `fix_required` ou `kill_overlay`
4. Documenter dans `reports/PHASE31_REVIEW_CHECKLIST.md`

## Interdictions Phase 30

- Pas de live / triple opt-in
- Pas de modification `execution.py`, `risk.py`, `config.yaml`
- Pas de tuning seuils funding/basis
- Pas de merge master automatique

## Fin Phase 30 — livrables attendus

- `reports/phase29_observation_metrics/summary.json` (dernier)
- `reports/PHASE29_OBSERVATION_MONITORING.md` (refresh)
- `reports/paper_observation_phase28/weekly_summary_*.md`
- Décision Phase 31 dans nouveau `PHASE31_NEXT_DECISION.md` (future)
