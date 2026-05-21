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

## Phase 26 — derivatives crowding research (addendum)

- Collectors publics : `src/data/collectors/binance_derivatives_public.py` (funding + OI Binance USDT-M ; liquidations = `blocked_data`).
- Caches gitignored : `data/collector_cache/funding_{TICKER}.json`, `oi_{TICKER}_{4h|1d}.json`.
- Build : `python scripts/build_derivatives_cache_phase26.py` ; audit : `scripts/audit_derivatives_cache_phase26.py`.
- Event study : `src/bot/derivatives_event_study.py` + `scripts/run_derivatives_event_study_phase26.py`.
- Overlay crowding : `src/bot/crowding_overlay.py` + `scripts/run_crowding_overlay_tournament_phase26.py` (stratégies Phase 23 uniquement).
- Walk-forward : `scripts/run_crowding_walkforward_phase26.py`.
- Verdicts autorisés : `kill`, `blocked_data`, `weak`, `overlay_only`, `validation_candidate`, `paper_candidate_derivatives` (recherche — pas live).
- Micro-live : **NO-GO** (`reports/MICRO_LIVE_GO_NO_GO_PHASE26.md`).
- Synthèse : `reports/PHASE26_DERIVATIVES_CROWDING_BLOCK.md`.

## Phase 27 — derivatives basis + overlay autopsy (addendum)

- Basis collector : `src/data/collectors/binance_basis_public.py` (spot vs mark-price perp, aligné 4h).
- Caches gitignored : `data/collector_cache/basis_{TICKER}_{4h|1d}.json`.
- Build : `python scripts/build_basis_cache_phase27.py` ; manifest : `reports/data_manifests_phase27/basis_readiness.json`.
- Overlay funding+basis : `src/bot/basis_crowding_overlay.py` + `scripts/run_basis_overlay_tournament_phase27.py`.
- OI depth audit : `scripts/audit_derivatives_depth_phase27.py` → OI **experimental** si <500 rows / <180j (exclu des gates `validation_candidate`).
- ETH 4h autopsy (3 cibles Phase 26 overlay_only) : `scripts/run_eth4h_overlay_autopsy_phase27.py`.
- Verdicts autopsy : `useful_overlay` | `decorative` | `kill_overlay`.
- Verdicts tournoi : `kill`, `blocked_data`, `weak`, `overlay_only` — **validation_candidate = 0** (OI experimental).
- Micro-live : **NO-GO** (`reports/MICRO_LIVE_GO_NO_GO_PHASE27.md`).
- Synthèse : `reports/PHASE27_DERIVATIVES_BASIS_OVERLAY.md`.

## Phase 28 — ETH 4h overlay paper observation (addendum)

- Daemon observation-only : `scripts/run_overlay_observation_daemon_phase28.py` (`--observation-only` default true).
- Cibles : ETH 4h `trend_following/baseline` + `ema_crossover/baseline` avec overlay `funding_basis`.
- Moteur : `src/bot/overlay_observation_engine.py` (cache-only, paper sim local).
- Shadow compare : `src/bot/overlay_shadow_compare.py` → `shadow_comparison.jsonl`.
- Kill criteria : `src/bot/overlay_observation_kill.py` + `reports/paper_observation_phase28/KILL_CRITERIA.md`.
- Flag stop : `reports/paper_observation_phase28/STOP_OBSERVATION`.
- Rapports : `scripts/generate_overlay_observation_report_phase28.py` → `daily_summary_*.md` / `weekly_summary_*.md`.
- État : `reports/paper_observation_phase28/{strategy}_{variant}/`.
- Micro-live : **NO-GO** (`reports/MICRO_LIVE_GO_NO_GO_PHASE28.md`) — besoin 2–4 semaines observation.
- Setup : `reports/PHASE28_SETUP.md` ; synthèse : `reports/PHASE28_ETH4H_OVERLAY_OBSERVATION.md`.
