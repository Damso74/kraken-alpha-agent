# Phase 17 — Next steps

**Date :** 2026-05-20

## Recommandation : Phase 18 (regime router)

1. Peupler caches 4h/1h pour walk-forward multi-TF complet.
2. Étendre historique daily ETH ≥545 barres pour fenêtres WF.
3. Lancer Phase 18 — regime router backtest.

## Blockers restants

| Blocker | Impact |
|---------|--------|
| Caches 4h/1h absents | 36/54 runs → blocked_data |
| ETH daily < 545 bars | insufficient_candles |
| 0 paper_candidate_walkforward | Attendu sans tuning |

## Non-goals (respectés)

- Pas de live trading
- Pas de merge master
- Pas de deploy
