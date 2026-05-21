# Observation weekly review — {{ISO_WEEK}}

> **PAPER OBSERVATION ONLY — no live trading.**

## Summary

| Target | Equity USD | Decisions | Trades | Block rate | Kill? |
|--------|------------|-----------|--------|------------|-------|
| trend_following_baseline | | | | | |
| ema_crossover_baseline | | | | | |

## Global

- STOP_OBSERVATION: absent / ACTIVE (reason: …)
- Stale data events: 
- Errors (tail): 

## Shadow proxies (week delta)

| Target | Missed upside bars | Avoided drawdown bars | Blocks | Reductions |
|--------|-------------------|----------------------|--------|------------|
| trend_following_baseline | | | | |
| ema_crossover_baseline | | | | |

## Kill criteria status

| Criterion | Threshold | trend_following | ema_crossover |
|-----------|-----------|-----------------|---------------|
| Block rate (30 barres) | ≤ 60% | | |
| Min trades | ≥ 5 | | |
| Incoherent blocks | < 3 | | |
| Equity gap vs standalone | ≥ −5 pp | n/a | n/a |
| Stale derivatives | none | | |

## Operator notes

- Cache refresh done: yes / no
- Anomalies observed: 
- Decision: continue_observation / fix_required / kill_overlay

## Commands used

```powershell
python scripts/generate_overlay_observation_report_phase28.py --weekly --all-targets
python scripts/aggregate_observation_metrics_phase29.py
```
