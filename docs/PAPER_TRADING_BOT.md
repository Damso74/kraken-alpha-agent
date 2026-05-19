# Paper trading bot (Phase 14 MVP)

Bot de backtest **papier uniquement** — aucun ordre live, aucune clé API.

## Démarrage rapide

```powershell
cd kraken-alpha-agent
.\.venv\Scripts\Activate.ps1
python -m pytest tests/test_paper_engine.py tests/test_strategy_tournament_phase14.py -q
python scripts/run_strategy_tournament.py --help
```

## Architecture

- Code : `src/bot/` (moteur) + `src/strategies/{base,trend_following,breakout,mean_reversion,grid}.py`
- Tournoi : `scripts/run_strategy_tournament.py`
- Données : `data/collector_cache/ohlc_daily_{TICKER}.json` (gitignored) ou candles synthétiques en tests

## Paramètres risk par défaut

| Paramètre | Valeur |
|-----------|--------|
| max_position_fraction | 0.25 |
| max_total_exposure | 0.50 |
| max_daily_loss_pct | 0.03 |
| max_drawdown_pct | 0.15 |
| max_trades_per_day | 5 |
| min_cash_reserve | 0.10 |

## Exécution simulée

- Achat : `price * (1 + slippage_bps/10000)`
- Vente : `price * (1 - slippage_bps/10000)`
- Frais : `notional * fee_bps/10000`

## Fichiers interdits

Ne pas modifier pour intégrer le bot papier : `config.yaml`, `src/execution.py`, `src/risk.py`, `src/futures_kraken_cli.py`, `web/`.

## Verdicts tournoi

Voir `src/bot/metrics.py`. `micro_live_candidate` nécessite `allow_micro_live=True` (désactivé par défaut).
