# Final QA — Phase 30

**Date :** 2026-05-21  
**Branche :** `phase30/vps-observation-cron`

## Checklist

| Item | Status |
|------|--------|
| Branche `phase30/vps-observation-cron` depuis phase29 | PASS |
| `scripts/ops_run_observation_once_phase30.sh` | PASS |
| `scripts/ops_run_observation_once_phase30.ps1` | PASS |
| `src/bot/observation_ops_guards.py` | PASS |
| `tests/test_observation_ops_phase30.py` | PASS |
| QA once PowerShell (refresh + daemon + reports) | PASS |
| `summary.json` mis à jour | PASS |
| `ops_logs/YYYYMMDD_HHMMSS.log` créé | PASS |
| Legacy state WARNING si BTC/regime_router | PASS |
| Full pytest suite | PASS (green) |
| STOP_OBSERVATION | absent |
| execution.py / risk.py / futures_kraken_cli.py / config.yaml / web/ | UNCHANGED |
| Micro-live | NO-GO |

## Commands run

```powershell
git checkout -b phase30/vps-observation-cron
powershell -File scripts/ops_run_observation_once_phase30.ps1
python -m pytest tests/test_observation_ops_phase30.py -q
python -m pytest -q
git diff -- src/execution.py src/risk.py src/futures_kraken_cli.py config.yaml web/
```

## Decision

**`ready_for_vps_cron`** — déployer cron VPS (utilisateur, demain).

## Fichiers sensibles non modifiés

- `src/execution.py`
- `src/risk.py`
- `src/futures_kraken_cli.py`
- `config.yaml`
- `web/`
