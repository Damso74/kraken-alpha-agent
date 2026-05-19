# Phase 11 — Stablecoin supply pre-registered runs

Frozen thresholds only (z=±1.0, 7d/30d). OHLC via `--ohlc-source binance-public`.
No grid search. No profitability claim.

**Command (authoritative run):**

```powershell
python scripts/event_study_stablecoins.py --phase11 --days 365 `
  --ohlc-source binance-public --cache-path data/collector_cache/defillama.json
```

## Run 2026-05-19 18:27 UTC

| preregistration_id | metric | direction | events | BH rej | verdict |
|--------------------|--------|-----------|--------|--------|---------|
| P9-SC-001-PR-7d-high | supply_change_7d | high | 12 | 1 | weak evidence |
| P9-SC-001-PR-30d-high | supply_change_30d | high | 0 | 0 | blocked: insufficient events |
| P9-SC-001-PR-7d-low | supply_change_7d | low | 36 | 2 | weak evidence |
| P9-SC-001-PR-30d-low | supply_change_30d | low | 52 | 3 | weak evidence |

**Synthèse :** aucun seuil pré-enregistré n'atteint `candidate for OOS testing (NOT tradable)`.
Placebos shift +30j et wrong-direction lag bloquent la promotion malgré des rejets BH
sur certaines cellules (7d-low, 30d-low). Expansion 30d-high : 0 events → blocked.

> `candidate for OOS testing` ≠ tradable. Aucune claim de rentabilité.
