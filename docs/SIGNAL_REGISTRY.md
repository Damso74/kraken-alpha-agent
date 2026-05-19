# Signal registry (Phase 12)

Canonical list: **`reports/signal_registry.json`**.

Loader: `src/research/signal_registry.py` (read-only, no network).

## Purpose

- Document which hypotheses remain in scope after Phase 11 red team.
- Enforce `tradable=false` and `oos_allowed=false` for every entry.
- Provide stable `signal_id` / `hypothesis_id` keys for leaderboard rows.

## Validation

```powershell
pytest tests/test_signal_registry.py -q
```

`validate_registry()` fails on duplicate ids, missing `schema_version`, or
any `tradable: true` flag.
