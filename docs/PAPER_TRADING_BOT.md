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

## Phase 15 — multi-timeframe (addendum)

- Loader : `src/bot/data_loader.py` (`1d` → `ohlc_daily_*`, `4h` → `ohlc_4h_*`, `1h` → `ohlc_1h_*`).
- Presets verrouillés : `src/strategies/presets.py` (`phase15_1d` / `phase15_4h` / `phase15_1h`).
- Tournoi V2 : `python scripts/run_strategy_tournament.py --timeframes 1d 4h 1h --cache-only`.
- Verdict centralisé : `classify_strategy_verdict()` — inclut `insufficient_candles`, `weak` ; pas de `micro_live_candidate`.
- Rapport : `reports/STRATEGY_TOURNAMENT_PHASE15.md`.

## Phase 16 — strategy zoo (addendum)

- Nouvelles stratégies : `ema_crossover`, `donchian_breakout`, `rsi_mean_reversion`, `bollinger_mean_reversion`, `atr_breakout`.
- Overlay vol : `src/strategies/volatility_targeting.py` — flag tournoi `--vol-targeting on|off` (défaut `off`).
- Presets Phase 16 : `PHASE16_ZOO_PRESETS` + `PHASE16_VOL_TARGET_PRESETS` dans `src/strategies/presets.py`.
- Tournoi zoo : `python scripts/run_strategy_tournament.py --phase 16 --timeframes 1d 4h 1h --cache-only`.
- Cache manquant → `blocked_data` (manifest : `reports/data_manifests_phase16/ohlcv_intraday_readiness.json`).
- Rapport : `reports/STRATEGY_ZOO_PHASE16.md`.
