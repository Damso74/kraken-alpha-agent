# Fee sensitivity — Phase 22

- Grid: fees_bps=[0.0, 10.0, 25.0, 40.0], slippage_bps=[0.0, 5.0, 10.0]
- Runs: 972

## Interpretation counts

- **cost_sensitive_survives_moderate**: 27
- **no_edge_at_zero_fees**: 22
- **positive_across_grid**: 32

## Guide

- `no_edge_at_zero_fees`: Loses even at 0 bps — no raw edge
- `killed_by_costs`: Positive at 0 bps but dies at 40 bps — turnover/cost drag
- `cost_sensitive_survives_moderate`: Survives 10-25 bps band — low-freq candidate
- `positive_across_grid`: Positive across tested grid (rare; verify trades)
