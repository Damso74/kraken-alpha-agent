# Regime Router — Phase 18

**Date :** 2026-05-20

## Composants

- `src/bot/regime_features.py` — features explicables
- `src/bot/regime_classifier.py` — trend_up / range / high_vol / panic / unknown
- `src/bot/regime_router.py` — routing + `RegimeRouterStrategy`
- `scripts/run_regime_router_tournament.py` — compare router vs best_single vs buy_and_hold vs cash

## Run local

12 runs (2 assets × 3 TF × 4 modes). Caches 4h/1h → blocked_data honnête.

Outputs : `reports/regime_router_phase18/`

## Recommandation

Phase 19 paper daemon.
