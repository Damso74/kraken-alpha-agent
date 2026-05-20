# Phase 17 — Red team (Agent 90)

**Date :** 2026-05-20  
**Verdict :** **`safe_for_walkforward`**

## Checklist

| # | Risque | Statut | Notes |
|---|--------|--------|-------|
| 1 | Windows overlap | **pass** | `validate_no_overlap` + tests |
| 2 | Holdout contaminé par tuning | **pass** | Presets fixes Phase 16 ; pas de grid search |
| 3 | Paramètres modifiés post-résultats | **pass** | Aucun tuning |
| 4 | Trop peu de windows | **pass** | `failed_walkforward` si `< 3` windows |
| 5 | Une période domine | **pass** | `consistency_score` + `positive_window_rate` |
| 6 | Coûts inclus par fenêtre | **pass** | `ExecutionSimulator` fees/slippage |
| 7 | Stratégies comparées équitablement | **pass** | Même windows / mêmes frais |
| 8 | Data missing propre | **pass** | `blocked_data` / `insufficient_candles` |
| 9 | No live / no Kraken | **pass** | Cache-only |
| 10 | paper_candidate_walkforward trop facile | **pass** | Seuils stricts (≥60% positive, median>0, holdout pass) |

## Observations

- Run local : 0 `paper_candidate_walkforward` (ETH 1d insufficient_candles, BTC 1d weak, 4h/1h blocked_data).
- Comportement honnête attendu sans caches intraday complets.

## Décision

**`safe_for_walkforward`** — pas de `fix_required`.
