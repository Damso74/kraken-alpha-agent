# Phase 24 — Walk-forward holdout sensitivity

- Runs total: **432**
- Holdout fractions: [0.2, 0.3, 0.4]
- Window modes: ['rolling', 'expanding']
- Overlay (primary): **off**
- `validation_candidate`: **1**
- `paper_candidate` / `paper_candidate_walkforward`: **0** (forbidden)

## Hypothesis test

Phase 24 tests whether Phase 23 zero-candidate outcome was driven by:
1. short history (`--max-bars 500`),
2. strict WF holdout windows,
3. limited asset universe, or
4. absence of real alpha.

