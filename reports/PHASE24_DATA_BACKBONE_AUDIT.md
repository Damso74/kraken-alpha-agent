# Phase 24 — Data backbone audit

Generated: 2026-05-20T17:18:58Z UTC

## Summary

- Required pairs (BTC/ETH/SOL × 1d/4h): **2/6** data_ok
- Required complete: **False**
- Entries audited: **4**
- data_ok: **3**
- ideal bars (1d≥1000, 4h≥2000): **0**
- Longer than Phase 23 `--max-bars 500` cap: **3**

## Criteria

- data_ok: 1d ≥500 bars, 4h ≥1000 bars
- ideal: 1d ≥1000, 4h ≥2000
- Phase 23 factory used last **500** bars by default

## Inventory

| asset | tf | bars | data_ok | ideal | first | last | Δ vs P23 cap |
|-------|-----|------|---------|-------|-------|------|--------------|
| BTC | 1d | 550 | True | False | 2020-01-01 | 2021-07-03 | 50 |
| BTC | 4h | 1050 | True | False | 2020-01-01 | 2020-06-23 | 550 |
| XRP | 1d | 510 | True | False | 2020-01-01 | 2021-05-24 | 10 |
| XRP | 4h | 0 | False | False | None | None | 0 |
