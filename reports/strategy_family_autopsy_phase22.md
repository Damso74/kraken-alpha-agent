# Strategy family autopsy — Phase 22

Diagnostic verdicts only — **not** tuning recommendations.

| Family | Verdict | Tournament | Walk-forward | Fee grid | Rationale |
|--------|---------|------------|--------------|----------|-----------|
| Trend / EMA / Donchian | **too_unstable** | pc=0 br=11 it=10 | unstable=15 weak=12 | no_edge=6 costly=0 | walk-forward unstable 15/27 |
| Breakout / ATR | **keep_for_tuning** | pc=0 br=5 it=5 | unstable=4 weak=14 | no_edge=3 costly=0 | weak but not catastrophic (median -0.8%) |
| RSI / Bollinger / MR | **kill** | pc=0 br=21 it=6 | unstable=1 weak=26 | no_edge=10 costly=0 | blocked_risk=21/27, median return=-13.7% |
| Grid | **keep_for_tuning** | pc=0 br=2 it=5 | unstable=0 weak=9 | no_edge=3 costly=0 | weak but not catastrophic (median 1.9%) |
| Vol targeting (overlay) | **keep_as_overlay** | pc=0 br=0 it=0 | unstable=0 weak=0 | no_edge=0 costly=0 | overlay not exercised in Phase 21 baseline (vol_targeting=off) |
| Regime router | **keep_as_overlay** | pc=0 br=0 it=0 | unstable=0 weak=0 | no_edge=0 costly=0 | 1d return +50% but blocked_risk; overlay/risk-reduction only (see regime_router_perf) |

## Verdict legend

- `kill` — no evidence of edge under current rules
- `keep_for_tuning` — marginal signal; Phase 23 may explore params (not post-hoc save)
- `keep_as_overlay` — vol targeting / router overlay only
- `needs_different_timeframe` — sparse trades on 1d, wrong freq on 1h
- `too_costly` — turnover eats gross at realistic fees
- `too_unstable` — walk-forward windows disagree
