# Phase 28 — Next decision

## Recommandation immédiate

**Lancer observation 2–4 semaines** (Track A) avant toute décision micro-live ou Phase 29 data depth.

```powershell
python scripts/run_overlay_observation_daemon_phase28.py `
  --run-all-targets --mode loop --interval-seconds 14400 `
  --allow-infinite-loop --cache-only
```

Rapport daily cron + weekly rollup.

## Phase 29 — options après 4 semaines

| Option | Condition | Action |
|--------|-----------|--------|
| **A — Continuer observation** | Kill criteria OK, shadow utile | Prolonger 4 semaines, affiner kill thresholds |
| **B — Data depth** | OI <500 rows, basis gaps | Phase 29 rebuild caches + OI depth audit |
| **C — Micro-live review** | ≥14j obs, equity gap ≥−5pp, block rate <60% | Revoir NO-GO Phase 28 (toujours PEDSL-CY blocked pour xStocks) |
| **D — Kill overlay** | Kill criteria récurrents | Retirer funding_basis overlay, garder baseline seul |

## Gates Phase 29

- Shadow : missed upside vs avoided drawdown documentés sur ≥30 barres 4h.
- Paper equity overlay vs standalone sur fenêtre glissante.
- Zéro `STOP_OBSERVATION` non expliqué.
- Micro-live reste NO-GO sans compte non-EU + validation_candidate historique.

## Non-prioritaire

- Optimisation paramètres overlay (interdit anti-curve-fit).
- Nouvelles stratégies / signaux.
