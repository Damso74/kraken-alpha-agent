# Regime router performance — Phase 22

Asset/timeframe: **BTC / 4h**
Candles: 6603 (processed 6548 bars)

| Mode | Elapsed (s) | bars/s | Verdict |
|------|-------------|--------|---------|
| uncached | 1624.5028 | 4.03 | blocked_risk |
| cached | 1843.3585 | 3.55 | blocked_risk |

**Speedup:** 0.88x with `cache_regime_features=True`

> Note: on full BTC 4h runs, speedup ≈1x because inner sub-strategy `on_bar` dominates; feature precompute removes redundant regime math only.

## Phase 21 gap

Phase 21 regime router rerun was **1d only** (17k+ 1h bars too slow uncached).
This benchmark completes **4h** with feature precompute.
