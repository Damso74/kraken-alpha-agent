# Phase 15 baseline (Agent 64)

**Date :** 2026-05-19  
**Branche :** `phase15/intraday-tournament-v2` (depuis `phase14/trading-bot-mvp`)  
**Commit de référence :** `f05369b` — feat(bot): Phase 14 paper trading MVP and strategy tournament

## Décision

**`proceed_phase15`** — baseline Phase 14 verte ; fichiers sensibles intacts.

## Git

| Check | Résultat |
|-------|----------|
| Branche active | `phase15/intraday-tournament-v2` |
| `config.yaml` diff | **vide** |
| `src/execution.py` diff | **vide** |
| `src/risk.py` diff | **vide** |
| `src/futures_kraken_cli.py` diff | **vide** |
| `web/` diff | **vide** |
| Master merge | **non** |

## Tests rapides (pré-implémentation)

```
tests/test_paper_engine.py tests/test_execution_simulator.py tests/test_risk_manager.py tests/test_strategy_tournament_phase14.py — 9 passed
```

## Données intraday

| Asset | 1d (`ohlc_daily_*.json`) | 4h (`ohlc_4h_*.json`) | 1h (`ohlc_1h_*.json`) |
|-------|--------------------------|------------------------|------------------------|
| BTC | présent | absent → `blocked_data` | absent → `blocked_data` |
| ETH | présent | absent → `blocked_data` | absent → `blocked_data` |
| SOL | absent → `blocked_data` | absent | absent |

Pas de téléchargement réseau — cache-only.

## Recommandation

**Proceed** — implémenter `data_loader`, `presets`, tournoi V2, métriques Phase 15 sur cette branche uniquement.
