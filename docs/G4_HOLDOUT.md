# G4 — Temporal hold-out (Phase 12)

Implementation: `src/research/holdout.py`  
CLI flag: `--enable-holdout` on event-study scripts via `scripts/_event_study_common.py`.

## Policy

- Default test fraction: **30 %** of daily candles (chronological tail).
- Reference cell for Wikipedia basket: `realized_vol` / `post_3`.
- Reference cell for return-based studies: `return` / `post_7`.
- **Pass (oos_survives):** BH rejection on the test partition **or**
  empirical placebo `p < 0.05` on the test partition for the reference cell.
- **Embargo (optional):** `embargo_days` drops train events within N calendar days
  before the split and test events within N days after the split (`apply_embargo`).
  JSON reports use `embargo_days_requested` / `embargo_days_applied`.
- Any script verdict of `candidate for OOS*` is **downgraded** to `weak evidence`
  when hold-out fails (`ELIG_G4_FAIL_OOS`).

## Tests

```powershell
pytest tests/test_event_study_oos.py -q
```

Aligned with `docs/PAPER_OBSERVATION_DESIGN.md` gate G4 and
`docs/SIGNAL_REJECTION_POLICY.md`.
