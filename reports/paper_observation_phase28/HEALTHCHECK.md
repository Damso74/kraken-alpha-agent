# Observation healthcheck (Phase 30.4)

> Generated: 2026-05-21T10:34:58.217638+00:00 UTC

**Overall status:** `WARNING`

- Fail checks: **0**
- Warning checks: **2**
- Pass checks: **14**
- Alerts critical: **0**
- Cron active: **False**

## Checks

- [PASS] `stop_observation`: STOP_OBSERVATION absent
- [PASS] `summary_present`: summary loaded from summary.json
- [PASS] `targets_present`: target_count=2
- [PASS] `observation_only`: observation_only=true
- [PASS] `state_eth_4h_trend_following_baseline`: trend_following_baseline: ETH 4h metadata OK
- [PASS] `state_eth_4h_ema_crossover_baseline`: ema_crossover_baseline: ETH 4h metadata OK
- [PASS] `state_legacy`: no legacy state metadata warnings
- [PASS] `alerts_present`: alerts.json loaded
- [PASS] `alerts_critical`: no critical alerts
- [PASS] `alerts_warning`: no warning alerts
- [PASS] `ops_log_freshness`: latest log 20260521_101417.log is 0.3h old
- [PASS] `dashboard_present`: dashboard at dashboard.html
- [PASS] `dashboard_freshness`: dashboard is 0.2h old
- [WARNING] `last_processed_trend_following_baseline`: last_processed_timestamp age 26.6h
- [WARNING] `last_processed_ema_crossover_baseline`: last_processed_timestamp age 26.6h
- [PASS] `no_new_candle_info`: only no_new_candle info alerts (awaiting next 4h bar)
