# Phase 16 — Strategy Zoo V1

**Date :** 2026-05-19  
**Branche :** `phase16/strategy-zoo-v1`

## Stratégies (9)

| # | Nom | Type | Fichier |
|---|-----|------|---------|
| 1 | trend_following | trend | Phase 14 |
| 2 | breakout | breakout | Phase 14 |
| 3 | mean_reversion | mean rev | Phase 14 |
| 4 | grid | grid | Phase 14 |
| 5 | ema_crossover | trend | **nouveau** |
| 6 | donchian_breakout | breakout | **nouveau** |
| 7 | rsi_mean_reversion | mean rev | **nouveau** |
| 8 | bollinger_mean_reversion | mean rev | **nouveau** |
| 9 | atr_breakout | breakout | **nouveau** |

**Overlay optionnel :** `volatility_targeting` (`--vol-targeting on`).

## Commande tournoi

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/run_strategy_tournament.py --phase 16 --assets BTC ETH --timeframes 1d --cache-only
```

## Résultats locaux (daily BTC+ETH, cache réel)

| Métrique | Valeur |
|----------|--------|
| Runs | 18 (9 strat × 2 assets) |
| paper_candidate | 0 |
| insufficient_trades | 10 |
| blocked_risk | 7 |
| blocked_costs | 1 |
| Output | `reports/strategy_tournament_phase16/` |

## Paramètres par défaut

- cash 1000, fees 40 bps, slippage 5 bps
- max drawdown gate 15%, max position 25%, max exposure 50%
- no short

## Données

Manifest : `reports/data_manifests_phase16/ohlcv_intraday_readiness.json`  
Daily BTC/ETH ✅ — 4h/1h/SOL ❌ `blocked_data`.
