# Phase 27 — Next decision

## Gates

| Gate | Count |
|------|-------|
| validation_candidate | **0** |
| paper_candidate_derivatives | **0** |
| useful_overlay (ETH autopsy) | **2** |
| decorative (ETH autopsy) | **1** |

## Options

### 28A — Paper observation overlay (recommended)
- Wire ETH 4h `trend_following/baseline` + `ema_crossover/baseline` with **funding+basis overlay** into paper daemon observation mode.
- No live, no micro-live; journal overlay decisions only.
- Rationale: autopsy `useful_overlay` + tournament `overlay_only` on same cells.

### 28B — Better derivatives data
- Integrate documented long-history OI (paid aggregator or exchange with history API).
- Prerequisite for OI-inclusive validation_candidate gates.
- Defer until 28A paper obs completes without regression.

### 28C — Stablecoin weekly macro
- Unrelated macro sleeve; lower priority vs overlay validation on ETH 4h.

## Recommendation

**Proceed with 28A** — paper observation overlay on the two ETH 4h useful_overlay targets. Keep OI experimental; do not promote to validation_candidate until 28B data depth resolved.
