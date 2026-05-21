# Phase 27 — Derivatives basis + overlay

**Question:** Do derivatives improve **risk-adjusted return** of existing ETH 4h strategies, or is the overlay decorative?

**Answer (cache run 2026-05-21):** Partially useful as a **risk overlay**, not alpha. Funding+basis beats funding-only on 4/8 cells; ETH 4h autopsy: 2/3 `useful_overlay`, 1/3 `decorative`. **0 validation_candidate.**

## Sub-phases

| Axis | Deliverable | Status |
|------|-------------|--------|
| A | Basis spot-perp collector + cache | ✅ BTC/ETH 4h × 6603 rows |
| B | Funding + basis overlay tournament | ✅ 8 cells |
| C | OI depth audit | ✅ experimental (6/6) |
| D | ETH 4h overlay autopsy | ✅ 3 Phase-26 targets |

## Basis cache coverage

| Asset | TF | Rows | Status |
|-------|-----|------|--------|
| BTC | 4h | 6603 | available |
| ETH | 4h | 6603 | available |

Manifest: `reports/data_manifests_phase27/basis_readiness.json`

## Overlay tournament (4h, BTC+ETH)

| Verdict | Count |
|---------|-------|
| overlay_only | 4 |
| weak | 3 |
| kill | 1 |
| blocked_data | 0 |
| validation_candidate | **0** |

- **Best mode:** `funding_basis` on 4 cells (vs 0 funding-only, 4 baseline)
- Notable: ETH 4h trend_following slow/baseline + ema_crossover → `overlay_only` with funding+basis
- BTC 4h trend_following baseline → `kill` (overlay hurts return without DD benefit)

Matrix: `reports/phase27_basis_overlay/results_matrix.csv`

## ETH 4h autopsy (Phase 26 overlay_only targets)

| Strategy | Verdict |
|----------|---------|
| trend_following / slow | decorative |
| trend_following / baseline | **useful_overlay** |
| ema_crossover / baseline | **useful_overlay** |

Details: `reports/phase27_eth4h_overlay_autopsy/`

## OI depth

All OI series **experimental** (~30d Binance window). Excluded from validation_candidate gates. See `PHASE27_OI_DATA_DEPTH.md`.

## Micro-live

**NO-GO** — research only. See `MICRO_LIVE_GO_NO_GO_PHASE27.md`.

## Phase 28 recommendation

**28A — paper observation overlay** on ETH 4h trend_following baseline + ema_crossover (useful_overlay autopsy, funding+basis mode). Defer 28B (better OI data) until a documented long-history source exists.
