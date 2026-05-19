# Strategy tournament — Phase 14

## CLI

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/run_strategy_tournament.py --assets BTC ETH --timeframe 1d --cash 1000 --fees-bps 40 --slippage-bps 5 --output-dir reports/strategy_tournament_phase14
```

## Sorties

| Fichier | Contenu |
|---------|---------|
| `results.json` | Métriques + verdict + risk stats par (asset, strategy) |
| `trades.csv` | Fills avec fee_bps / slippage |
| `equity_curve.csv` | Courbe equity |
| `decisions.jsonl` | Signaux, risk, rejects |

## Run Phase 14.1 (2026-05-19)

**Commande :** tournoi ci-dessus sur `BTC` + `ETH`, cache Binance daily local (`data/collector_cache/ohlc_daily_*.json`).

| Asset | Cache | Statut |
|-------|-------|--------|
| BTC | `ohlc_daily_BTC.json` présent | `data_ok=true` |
| ETH | `ohlc_daily_ETH.json` présent | `data_ok=true` (pas de données inventées) |

**Verdicts (après correctif `blocked_risk` Phase 14.1) :**

| Run | Verdict | Raison principale |
|-----|---------|-------------------|
| BTC trend_following | `blocked_risk` | `risk_denial_rate=43.75%` (> 30 %) |
| BTC breakout | `blocked_costs` | `cost_drag_pct=100%` |
| BTC mean_reversion | `blocked_risk` | drawdown 15.6 % + denial rate 95 % |
| BTC grid | `blocked_costs` | `cost_drag_pct=100%` |
| ETH trend_following | `insufficient_trades` | 3 trades (< 5) |
| ETH breakout | `insufficient_trades` | 3 trades |
| ETH mean_reversion | `insufficient_trades` | 1 trade |
| ETH grid | `insufficient_trades` | 2 trades |

Aucun `micro_live_candidate` (interdit par défaut). Aucun `paper_candidate` sur ce run — frais 40 bps + PnL négatif.

## Correctif `blocked_risk` (Phase 14.1)

Avant : un seul deny risk → `blocked_risk` pour toute la stratégie.

Après : `blocked_risk` seulement si drawdown > 15 %, `risk_denial_rate` > 30 %, safety stop (drawdown/journalier), portefeuille invalide, grid > inventaire max, ou zéro fill avec denials massifs. Métriques exportées : `risk_denials_count`, `risk_denial_rate`, `risk_rules_triggered`, `stopped_by_risk`.

## Interprétation

Le tournoi reste un **filtre honnête** : résultats négatifs attendus avec frais élevés ; les verdicts distinguent coûts, risque structurel et manque de trades.
