# Phase 22 — Next decision

**Recommended track: 23A** (primary) + **23D** overlay exploration secondary

**23A — Low-frequency trend on 1d/4h only**: Drop 1h zoo runs; focus Donchian/breakout with min-hold; accept sparse trades.

**Secondary:** 23D — regime router as risk overlay on buy-and-hold, not standalone alpha.

## Options

| Track | When | Action |
|-------|------|--------|
| **23A** | Sparse 1d signals | Low-freq trend/breakout, drop 1h from zoo |
| **23B** | Family shows weak but not kill | Pre-registered WF params (max 3/family) |
| **23C** | Fee grid `killed_by_costs` dominates | Widen bands, halve turnover before new alpha |
| **23D** | Router positive but blocked_risk | Overlay on B&H, not standalone alpha |

## Explicit NO-GO (unchanged)

- Micro-live / live execution
- Post-hoc parameter tuning on Phase 21 losers
- New strategy families without Phase 22 diagnosis sign-off

## Evidence pointers

- Tournament: `reports/strategy_tournament_phase21_rerun/` (0 paper_candidate)
- Walk-forward: `reports/walkforward_phase21_rerun/` (0 paper_candidate_walkforward)
- This diagnosis: `reports/PERFORMANCE_DIAGNOSIS_PHASE22.md`
