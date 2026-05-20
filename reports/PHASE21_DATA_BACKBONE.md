# Phase 21 — Data backbone / intraday cache fill

**Date :** 2026-05-20  
**Branche :** `phase21/intraday-data-backbone`  
**Manifest :** `reports/data_manifests_phase21/ohlcv_backbone_manifest.json`

## Politique

- Sources **publiques uniquement** : Binance `/api/v3/klines` (pas de clé API).
- Pas de données inventées ; cache absent → `blocked_data` dans les tournois.
- Fichiers sous `data/collector_cache/` **gitignored** — ne pas committer de gros JSON marché.
- Builder : `python scripts/build_intraday_cache.py`
- Audit local (sans réseau) : `python scripts/audit_ohlcv_caches.py`

## Chemins cache (compatible `src/bot/data_loader.py`)

| Timeframe | Fichier | Intervalle (min) |
|-----------|---------|------------------|
| 1d | `ohlc_daily_{TICKER}.json` | 1440 |
| 4h | `ohlc_4h_{TICKER}.json` | 240 |
| 1h | `ohlc_1h_{TICKER}.json` | 60 |

## Profondeur cible

| Timeframe | Cible calendaire | Seuil `data_ok` (rows) |
|-----------|------------------|------------------------|
| 1h | ~2 ans | ≥ 17 000 |
| 4h | ~3 ans | ≥ 6 000 |
| 1d | ~5 ans | ≥ 1 800 |

## Peuplement manuel (réseau requis)

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/build_intraday_cache.py --assets BTC ETH SOL --timeframes 1d 4h 1h
python scripts/audit_ohlcv_caches.py
```

Vérification sans réseau :

```powershell
python scripts/build_intraday_cache.py --cache-only
python scripts/audit_ohlcv_caches.py
```

## Résultat build local (2026-05-20)

| Asset | 1d | 4h | 1h |
|-------|-----|-----|------|
| BTC | 1831 | 6603 | 17650 |
| ETH | 1831 | 6603 | 17650 |
| SOL | 1831 | 6603 | 17650 |

## Tests

`tests/test_intraday_cache_backbone_phase21.py` — schéma manifest, audit sur fixtures, fetch injecté Binance.
