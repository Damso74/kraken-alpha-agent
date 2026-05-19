# Bot architecture audit — Phase 14 (Agent 54)

## Objectif

Cartographier le code existant vs le MVP papier `src/bot/` (stdlib-first, sans Kraken live).

## Inventaire existant

| Domaine | Fichiers | Rôle | Réutilisation Phase 14 |
|---------|----------|------|------------------------|
| Backtest replay | `src/backtest.py` | OHLC → features → ensemble → risk live | **Inspirer** types `Candle` ; **ne pas importer** (couplage `src.risk`, config) |
| Portfolio live | `src/portfolio.py` | SQLite + Kraken snapshot | **Séparer** — nouveau `src/bot/portfolio.py` |
| Risk live | `src/risk.py` | Gates compétition / futures | **Interdit** (fichier protégé) — `src/bot/risk_manager.py` |
| Execution live | `src/execution.py` | CLI Kraken | **Interdit** — `src/bot/execution_simulator.py` |
| Stratégies votes | `src/strategies/{momentum,breakout,mean_reversion}.py` | `score(Features)` | **Étendre** fichiers breakout/MR avec classes bot ; nouvelles `trend_following.py`, `grid.py` |
| OHLC cache | `src/data/collectors/binance_public.py` | `load_ohlc_daily_cache` | **Réutiliser** pour tournoi (cache-only) |
| Scripts backtest | `scripts/backtest_xstocks.py`, `walk_forward_*.py` | xStocks / crypto WF | **Ne pas modifier** ; tournoi = `scripts/run_strategy_tournament.py` |

## Décisions d’architecture

1. **Namespace `src/bot/`** — moteur papier isolé du stack compétition.
2. **Stratégies** — interface `BaseStrategy` / `StrategySignal` dans `src/strategies/base.py` ; pas de dépendance à `Features` pour le MVP.
3. **Verdicts** — `src/bot/metrics.py` ; `micro_live_candidate` désactivé par défaut (`allow_micro_live=False`).
4. **Tournoi** — charge uniquement `data/collector_cache/ohlc_daily_{TICKER}.json` ; `blocked_data` si absent.

## Créations (nouveau)

- `src/bot/{orders,portfolio,execution_simulator,risk_manager,journal,metrics,paper_engine}.py`
- `src/strategies/{base,trend_following,grid}.py` + classes bot dans breakout/mean_reversion
- `scripts/run_strategy_tournament.py`
- Tests `tests/test_*` Phase 14 (19 tests ajoutés)

## Risques résiduels

| Risque | Mitigation |
|--------|------------|
| Confusion `src/portfolio` vs `src/bot/portfolio` | Doc `docs/PAPER_TRADING_BOT.md` |
| `blocked_risk` si risk deny partiel | Verdict honnête ; pas de promotion live |
| Cache OHLC absent en CI | Tests 100 % synthétiques |

## Verdict audit

**Réutiliser** cache OHLC + patterns backtest ; **créer** stack bot papier dédiée. Aucune modification des modules live protégés.
