# Final QA — Phase 28

**Date :** 2026-05-21  
**Branche :** `phase28/eth4h-overlay-paper-observation`

## Checklist

| Item | Status |
|------|--------|
| Daemon once sur cache réel (2 cibles) | PASS |
| Shadow comparison jsonl écrit | PASS |
| State persisté (state.json, equity_curve) | PASS |
| observation_only default True | PASS |
| Kill criteria module + KILL_CRITERIA.md | PASS |
| STOP_OBSERVATION flag | PASS |
| Daily/weekly report script | PASS |
| Tests Phase 28 (9 new) | PASS |
| Full pytest suite | PASS (862+) |
| execution.py / risk.py / config.yaml / web/ | UNCHANGED |
| Micro-live | NO-GO |

## Demo once output (cache ETH 4h)

**trend_following + funding_basis**
- equity: 1112.09 USD, trades: 114
- shadow: hold / allow / neutral, basis_z=1.43

**ema_crossover + funding_basis**
- equity: 965.88 USD, trades: 100
- shadow: hold / allow / neutral, basis_z=1.43

## Fichiers sensibles non modifiés

- `src/execution.py`
- `src/risk.py`
- `src/futures_kraken_cli.py`
- `config.yaml`
- `web/`
