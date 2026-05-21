# Phase 26A — Derivatives data collectors

Public-only Binance USDT-M endpoints (no API keys).

- Cache entries available: **6** / 10
- Liquidations: **blocked_data**

## Sources

- Funding: `fapi/v1/fundingRate`
- Open interest: `futures/data/openInterestHist`
- Liquidations: blocked — short rolling window only on Binance public API
- OI history: Binance caps lookback (~30 days); use `--oi-days 30` on build script

## Build

```powershell
python scripts/build_derivatives_cache_phase26.py --assets BTC ETH
python scripts/audit_derivatives_cache_phase26.py
```
