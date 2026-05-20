# Regime router performance — Phase 22

Asset/timeframe: **BTC / 4h**
Candles: 6603 (processed 500 bars)

| Mode | Elapsed (s) | bars/s | Verdict |
|------|-------------|--------|---------|
| uncached | 9.9181 | 50.41 | blocked_costs |
| cached | 9.7801 | 51.12 | blocked_costs |

**Speedup:** 1.01x with `cache_regime_features=True`

> Note: on full BTC 4h runs, speedup ≈1x because inner sub-strategy `on_bar` dominates; feature precompute removes redundant regime math only.

## Phase 21 gap

Phase 21 regime router rerun was **1d only** (17k+ 1h bars too slow uncached).
This benchmark completes **4h** with feature precompute.
