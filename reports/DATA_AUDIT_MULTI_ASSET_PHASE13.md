# Data audit multi-asset OHLCV (Agent 45)

**Date :** 2026-05-19  
**Décision :** `partial_assets_available` (BTC + ETH OK, SOL bloqué)

## Synthèse

| Asset | Statut | Rows (fenêtre 365j) | Cache SHA256 (16 premiers) | Volume |
|-------|--------|---------------------|----------------------------|--------|
| BTC | available | 371 | `32d7b6b00974ffb4` | oui |
| ETH | available | 371 | `7dc8e8c6fb07020c` | oui |
| SOL | **blocked_data** | — | fichier absent | — |

Manifest canonique : `reports/data_manifests_phase13/ohlcv_multi_asset_manifest.json`.

## BTC

- **Source :** `data/collector_cache/ohlc_daily_BTC.json` (Binance public cache, non commité en prod jury).  
- **Intervalle :** 1d UTC.  
- **Couverture fenêtre 365j :** ~371 bougies (≥ 365 requis).  
- **Limitation :** cache local — reproductible via hash, pas via commit git du JSON.

## ETH

- Même schéma que BTC ; alignement temporel coïncident (mêmes timestamps boundary sur la fenêtre récente).

## SOL

- **blocked_reason :** `ohlc_daily_SOL.json` absent du répertoire cache.  
- **Action :** ne pas fabriquer de bougies ; marquer `blocked_data` dans le run JSON et le leaderboard.  
- **Fallback documenté :** analyse BTC+ETH uniquement ; généralisation multi-actif **non** revendiquée.

## Tests

- Aucun appel réseau dans les tests unitaires.  
- Audit local via `fetch_ohlc_daily_cache_only` + `ohlc_cache_row_count` (`_provenance.py`).

## Conformité Phase 13

- Pas de commit de `data/collector_cache/ohlc_daily_*.json` réels.  
- Provenance attachée aux variantes dans `volume_shock_protocol_a_365d.json`.
