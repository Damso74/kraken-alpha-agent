# Phase 15 — Intraday data audit (Agent 65)

**Date :** 2026-05-19  
**Branche :** `phase15/intraday-tournament-v2`  
**Manifest :** `reports/data_manifests_phase15/ohlcv_timeframe_manifest.json`

## Politique

- Pas de téléchargement réseau depuis le tournoi (`--cache-only`).
- Cache manquant → `blocked_data` (aucune série inventée).
- Colonnes requises par candle : `timestamp`, `open`, `high`, `low`, `close`, `volume`.

## Chemins cache

| Timeframe | Fichier attendu | Intervalle (min) |
|-----------|-----------------|------------------|
| 1d | `data/collector_cache/ohlc_daily_{TICKER}.json` | 1440 |
| 4h | `data/collector_cache/ohlc_4h_{TICKER}.json` | 240 |
| 1h | `data/collector_cache/ohlc_1h_{TICKER}.json` | 60 |

## Audit BTC / ETH / SOL

| Asset | 1d | 4h | 1h |
|-------|----|----|-----|
| **BTC** | ✅ 736 candles, sha256 `32d7b6b0…` | ❌ absent | ❌ absent |
| **ETH** | ✅ 371 candles, sha256 `7dc8e8c6…` | ❌ absent | ❌ absent |
| **SOL** | ❌ absent | ❌ absent | ❌ absent |

## Décision

**`partial_assets_available`** — seul le daily BTC/ETH est exploitable ; 4h/1h et SOL restent `blocked_data` jusqu’à peuplement local du cache (hors commit git).

## Validation loader

`src/bot/data_loader.py` rejette : OHLC invalide, timestamps dupliqués, ordre non monotone, mismatch `interval_minutes` fichier vs timeframe demandé.
