# Red team gating (Phase 12)

Phase 12 replaces hard-coded red team lookups in `reports/_build_leaderboard.py`
with **`reports/red_team_verdicts.json`**.

## Rules

1. Patterns use `fnmatch` against `signal` (e.g. `wikipedia_*`, `volume_shock_*`).
2. Statuses in `blocks_oos_statuses` (`fail`, `revoked`, …) **cap** any
   `candidate for further OOS testing` verdict to `weak evidence`.
3. `warning` does not block by itself but documents caveats in the leaderboard.
4. No signal in the registry may set `tradable: true` or `oos_allowed: true`
   during methodology sprints.

## Rebuild

```powershell
python reports/_build_leaderboard.py --phase12
```

See also `reports/RED_TEAM_GATING_PHASE12.md` and `reports/RED_TEAM_PHASE11.md`.
