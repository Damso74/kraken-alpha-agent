# Walk-forward Tournament — Phase 17

**Date :** 2026-05-20  
**Branche :** `phase17/walkforward-tournament`

## Objectif

Remplacer le backtest unique par des fenêtres roulantes train / validation / holdout avec métriques de stabilité.

## Composants

| Module | Rôle |
|--------|------|
| `src/bot/walkforward.py` | Split engine, embargo, rolling windows |
| `src/bot/walkforward_metrics.py` | Agrégats + verdicts WF |
| `scripts/run_walkforward_tournament.py` | Runner cache-only |

## Paramètres pré-déclarés

| TF | train | validation | holdout | step |
|----|-------|------------|---------|------|
| 1d | 365 | 90 | 90 | 30 |
| 4h | 2190 | 540 | 540 | 180 |
| 1h | 8760 | 2160 | 2160 | 720 |

## Run local (cache réel)

```
python scripts/run_walkforward_tournament.py --assets BTC ETH --timeframes 1d 4h 1h --strategies all --cache-only
```

**54 runs** (2 assets × 3 TF × 9 stratégies)

| Verdict | Count |
|---------|-------|
| blocked_data | 36 |
| insufficient_candles | 9 |
| weak | 9 |
| paper_candidate_walkforward | 0 |

## Outputs

- `reports/walkforward_phase17/results.json`
- `reports/walkforward_phase17/results_matrix.csv`
- `reports/walkforward_phase17/window_results.csv`
- `reports/walkforward_phase17/equity_by_window.csv`

## Recommandation

Phase 18 (regime router) peut démarrer — red team `safe_for_walkforward`.
