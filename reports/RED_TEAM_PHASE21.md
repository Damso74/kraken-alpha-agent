# Red team — Phase 21

**Date :** 2026-05-20

## Checks

| Risque | Statut |
|--------|--------|
| Données inventées / fake OHLC | ✅ Binance public klines uniquement ; absent → `blocked_data` |
| Lookahead / leakage dans builder | ✅ Append-only merge par timestamp ; pas de shuffle |
| Secrets dans commit | ✅ `data/collector_cache/*.json` gitignored ; pas de `.env` |
| Gros JSON marché commités | ✅ `.gitignore` `data/collector_cache/*` |
| Live / Kraken write API | ✅ Aucun appel ; tournois `--cache-only` |
| Fichiers sensibles modifiés | ✅ `config.yaml`, `execution.py`, `risk.py`, `futures_kraken_cli.py`, `web/` **non touchés** |

## Bug corrigé

- `parse_ohlc_candle_rows` normalisait les timestamps intraday à minuit UTC → audit sous-comptait 1h/4h. Corrigé via `normalize_to_day` conditionnel sur `interval_minutes`.

## Résidu

- Source OHLC tournoi = **Binance spot USDT**, pas Kraken — documenté ; acceptable pour paper/backtest, pas pour PnL jury Kraken.
