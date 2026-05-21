# Observation ops digest (Phase 30.4)

> Generated: 2026-05-21T10:34:59.376489+00:00 UTC

## Status

| Field | Value |
|-------|-------|
| Overall | `WARNING` |
| Healthcheck | `warning` |
| Next action | **`continue_observation`** |
| STOP flag | False |
| Critical alerts | 0 |
| Warning alerts | 0 |
| Latest ops log | 20260521_101417.log |
| Log age (h) | 0.34 |

## Targets

| Target | Decisions | Trades | Stale | Overlay ret % | Block rate |
|--------|-----------|--------|-------|---------------|------------|
| trend_following_baseline | 1 | 114 | 0 | 11.2088 | 0.0 |
| ema_crossover_baseline | 1 | 100 | 0 | -3.4116 | 0.0 |

## Alerts

- [INFO] `no_new_candle` (trend_following_baseline): decision_count=1 — duplicate-candle idempotence or awaiting next 4h bar
- [INFO] `no_new_candle` (ema_crossover_baseline): decision_count=1 — duplicate-candle idempotence or awaiting next 4h bar

## Next action

**`continue_observation`** — dry-run notification only (no email/webhook).

Weekly rollup: `weekly_summary_2026-W21.md`
