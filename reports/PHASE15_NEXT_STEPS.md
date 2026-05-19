# Phase 15 — Prochaines étapes

## Données (priorité)

1. Peupler localement (sans commit) :
   - `data/collector_cache/ohlc_4h_{BTC,ETH}.json`
   - `data/collector_cache/ohlc_1h_{BTC,ETH}.json`
   - `data/collector_cache/ohlc_daily_SOL.json` (optionnel)
2. Re-lancer le tournoi `--cache-only` et mettre à jour `reports/data_manifests_phase15/ohlcv_timeframe_manifest.json`.

## Code

- Brancher un script cache-only existant (Binance public) si ajouté au repo — **pas** de fetch depuis le tournoi.
- Option : exporter la matrice verdict vers le dashboard **statique** (hors `web/` protégé) via JSON commité dans `reports/`.

## Non-objectifs

- Pas de merge `master`
- Pas de live / Kraken keys
- Pas de `micro_live_candidate`
- Pas d’optimisation de presets après résultats
