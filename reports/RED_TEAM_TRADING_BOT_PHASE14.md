# Red team — Trading bot Phase 14 (Agent 61)

| Module | Check | Statut | Notes |
|--------|-------|--------|-------|
| `src/bot/paper_engine.py` | Aucun import execution/Kraken | **pass** | Boucle locale uniquement |
| `src/bot/execution_simulator.py` | Slippage buy/sell + fee bps | **pass** | Formules spec |
| `src/bot/risk_manager.py` | Defaults spec (25/50/3/15/5/10%) | **pass** | Indépendant de `src.risk` |
| `src/bot/metrics.py` | `micro_live_candidate` off by default | **pass** | `allow_micro_live=False` |
| `src/bot/portfolio.py` | Short impossible (sell ≤ qty) | **pass** | `ValueError` si oversell |
| `src/strategies/grid.py` | Max 3 levels, 30% cap, no martingale | **pass** | Taille fixe par niveau |
| `scripts/run_strategy_tournament.py` | Pas d’appel réseau | **pass** | Cache fichier seulement |
| Tests | `network` / Kraken mock | **pass** | Fixtures synthétiques |
| `config.yaml` | Non modifié | **pass** | git diff vide |
| `web/` | Non modifié | **pass** | |
| Tournoi local BTC | Returns négatifs + blocked_risk | **warning** | Honnête — pas paper_candidate |
| Claims marketing | Pas de « live-ready » | **pass** | Verdicts limités |

## Attaques tentées

1. **Bypass live** — grep `kraken` / `execution` dans `src/bot/` → aucun.
2. **Curve-fit tournoi** — verdicts exigent min trades + seuils drawdown/return.
3. **Fee understatement** — `fee_bps` / `slippage_bps` exportés dans `results.json`.
4. **Secret leak** — aucun `.env` / clé dans nouveaux fichiers.

## fix_required

- Aucun bloquant.
- **warning** : `compute_verdict(..., risk_blocked=True)` si *une* denial risk — documenter pour le jury (comportement conservateur).

## Synthèse

**pass** avec warnings documentés — safe pour commit sur branche feature (pas master).
