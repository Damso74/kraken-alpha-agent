# Phase 29 — Observation monitoring

> Generated: 2026-05-21T10:21:35.106197+00:00 UTC

> **PAPER OBSERVATION ONLY — no live trading, no Kraken private API.**

## Global status

- Targets: **2**
- Total decisions: **2**
- Total trades (csv): **214**
- STOP_OBSERVATION: **absent**
- Kill criteria triggered: **False**
- observation_only: **True**

## trend_following_baseline

- Decisions: 1 | Shadow rows: 1
- Trades: 114
- Overlay decisions — allow: 1 | block: 0 | reduce: 0 | neutral: 0
- Block rate (on standalone signals): 0.00%
- Reduce rate (on decisions): 0.00%
- Stale data signals: 0 | Errors: 0

### Equity
- Overlay: **1112.09** USD (return from 1k: 11.2088%)
- B&H return proxy: 0.0%
- Standalone return: n/a (not persisted)
- Max drawdown (overlay curve): 0.0%

### Shadow proxies
- Missed upside bars: 0
- Avoided drawdown bars: 0
- Blocks / reductions: 0 / 0

### Kill criteria
- should_kill: **False**

## ema_crossover_baseline

- Decisions: 1 | Shadow rows: 1
- Trades: 100
- Overlay decisions — allow: 1 | block: 0 | reduce: 0 | neutral: 0
- Block rate (on standalone signals): 0.00%
- Reduce rate (on decisions): 0.00%
- Stale data signals: 0 | Errors: 0

### Equity
- Overlay: **965.88** USD (return from 1k: -3.4116%)
- B&H return proxy: 0.0%
- Standalone return: n/a (not persisted)
- Max drawdown (overlay curve): 0.0%

### Shadow proxies
- Missed upside bars: 0
- Avoided drawdown bars: 0
- Blocks / reductions: 0 / 0

### Kill criteria
- should_kill: **False**

## Refresh

```powershell
python scripts/aggregate_observation_metrics_phase29.py
```
