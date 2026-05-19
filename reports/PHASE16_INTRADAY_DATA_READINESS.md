# Phase 16 — Intraday data readiness (Agent 74)

**Date :** 2026-05-19  
**Branche :** `phase16/strategy-zoo-v1`  
**Manifest :** `reports/data_manifests_phase16/ohlcv_intraday_readiness.json`

## Politique

- Loader cache-only (`src/bot/data_loader.py`) — pas de réseau depuis le tournoi.
- Cache absent → `blocked_data` / `can_run_strategy_zoo: false`.
- Pas de `scripts/build_intraday_cache.py` : la source publique Binance du repo ne couvre que le **daily** (`src/data/collectors/binance_public.py`). Les timeframes 4h/1h ne sont pas fetchables sans extension réseau → **documenter blocked_data**, ne pas inventer.

## Audit BTC / ETH / SOL

| Asset | 1d | 4h | 1h |
|-------|----|----|-----|
| **BTC** | ✅ 736 candles | ❌ absent | ❌ absent |
| **ETH** | ✅ 371 candles | ❌ absent | ❌ absent |
| **SOL** | ❌ absent | ❌ absent | ❌ absent |

## Décision

**`partial_assets_available`** — tournoi Phase 16 exploitable sur **daily BTC/ETH** uniquement ; 4h/1h et SOL restent `blocked_data` jusqu'à peuplement local du cache (hors commit git).

## Tests

`tests/test_intraday_cache_readiness_phase16.py` — valide le manifest et le comportement `blocked_data` sur cache absent.
