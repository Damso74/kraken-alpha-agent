# Phase 21 — Data readiness gate

**Date :** 2026-05-20  
**Branche :** `phase21/intraday-data-backbone`  
**Manifest :** `reports/data_manifests_phase21/ohlcv_backbone_manifest.json`

## Critère `can_run_full_tournament`

**Vrai** lorsque **BTC** et **ETH** ont `data_ok: true` sur **1d**, **4h** et **1h**.

État après peuplement Binance public + audit local :

| Gate | Statut |
|------|--------|
| `can_run_full_tournament` | **true** |
| BTC 1d / 4h / 1h | ✅ |
| ETH 1d / 4h / 1h | ✅ |
| SOL 1d / 4h / 1h | ✅ (bonus) |

## Synthèse caches (audit 2026-05-20)

| Asset | 1d rows | 4h rows | 1h rows |
|-------|---------|---------|---------|
| BTC | 1831 | 6603 | 17650 |
| ETH | 1831 | 6603 | 17650 |
| SOL | 1831 | 6603 | 17650 |

Source : `binance_public_klines` — pas de clé API.

## Tournois relancés (cache-only)

| Script | Output | `blocked_data` | `paper_candidate` / WF |
|--------|--------|----------------|-------------------------|
| `run_strategy_tournament.py` | `reports/strategy_tournament_phase21_rerun` | **0** | **0** paper_candidate |
| `run_walkforward_tournament.py` | `reports/walkforward_phase21_rerun` | **0** | **0** paper_candidate_walkforward (20 unstable, 61 weak) |
| `run_regime_router_tournament.py` | `reports/regime_router_phase21_rerun` | **0** (1d only) | **0** |

**Note :** le tournoi regime router complet sur **1h/4h** dépasse un runtime raisonnable en local (~25+ min par asset/timeframe à cause de `RegimeRouterStrategy`). Le rerun Phase 21 documente **1d × 3 assets × 4 modes** ; relancer 4h/1h manuellement si besoin.

## CI sans réseau

- Builder + audit : tests hermetic (`tests/test_intraday_cache_backbone_phase21.py`).
- Caches réels : action manuelle `python scripts/build_intraday_cache.py` puis commit du manifest uniquement.
