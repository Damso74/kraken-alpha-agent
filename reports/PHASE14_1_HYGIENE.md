# Phase 14.1 — Hygiène pré-commit

**Date :** 2026-05-19  
**Branche :** `phase14/trading-bot-mvp`  
**Agent :** Phase 14.1 final hygiene

## 1. Tests

| Métrique | Valeur |
|----------|--------|
| `pytest --collect-only` | **669** tests collectés |
| `pytest -q` | **669 passed**, 0 failed |

### Écart vs baselines

| Référence | Count | Contexte |
|----------|-------|----------|
| Phase 13 (`PHASE13_BASELINE.md`) | 641+ / ~644 | Branche `posthackathon/research-lab-phase-3-10` — lab recherche, sans `src/bot/` |
| Phase 14 (`PHASE14_BASELINE.md`) | 593 | Premier jet bot MVP sur branche phase14 (moins de tests collectés qu’aujourd’hui) |
| Phase 14.1 (ce run) | **669** | +76 tests vs 593 : nouveaux modules `src/bot/`, 4 stratégies, tournoi, simulateur, journal, etc. |

**Explication :** pas de suppression de tests Phase 12/13 identifiée ; la différence 593 → 669 vient des **ajouts** Phase 14 (`test_bot_metrics`, `test_paper_engine`, `test_strategy_*`, `test_execution_simulator`, …). L’écart 644 → 669 sur la branche actuelle = ~25 tests bot + ajustements de collecte sur la même branche phase14.

## 2. Tournoi

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/run_strategy_tournament.py --assets BTC ETH --timeframe 1d --cash 1000 --fees-bps 40 --slippage-bps 5 --output-dir reports/strategy_tournament_phase14
```

**Exécuté :** oui (8 runs = 4 stratégies × 2 actifs).

## 3. Actifs

| Asset | Cache | Statut |
|-------|-------|--------|
| BTC | `ohlc_daily_BTC.json` | testé, `data_ok=true` |
| ETH | `ohlc_daily_ETH.json` | testé, `data_ok=true` |

Pas de `blocked_data` — les deux caches existent (pas de données ETH fictives).

## 4. Verdicts (post-fix `blocked_risk`)

| Strategy × Asset | Verdict |
|------------------|---------|
| trend_following × BTC | `blocked_risk` |
| breakout × BTC | `blocked_costs` |
| mean_reversion × BTC | `blocked_risk` |
| grid × BTC | `blocked_costs` |
| trend_following × ETH | `insufficient_trades` |
| breakout × ETH | `insufficient_trades` |
| mean_reversion × ETH | `insufficient_trades` |
| grid × ETH | `insufficient_trades` |

Verdicts autorisés observés : `blocked_risk`, `blocked_costs`, `insufficient_trades`. Pas de `micro_live_candidate`.

## 5. Correctif `blocked_risk`

- **Avant :** `risk_denied=True` sur un seul deny → tout le run en `blocked_risk`.
- **Après :** `RiskRunStats` + seuils dans `compute_verdict` : drawdown > 15 %, denial rate > 30 %, safety stop, exposition invalide, grid inventaire, zéro trade avec denials.
- **Fichiers :** `src/bot/metrics.py`, `src/bot/paper_engine.py`, `scripts/run_strategy_tournament.py`, tests `test_bot_metrics.py`, `test_strategy_tournament_phase14.py`.

## 6. Fichiers sensibles (`git diff`)

| Chemin | Diff |
|--------|------|
| `config.yaml` | vide |
| `src/execution.py` | vide |
| `src/risk.py` | vide |
| `src/futures_kraken_cli.py` | vide |
| `web/` | vide |

## 7. Staging (pré-commit)

**À inclure :** `src/bot/`, `src/strategies/`, `scripts/run_strategy_tournament.py`, `tests/`, `reports/*.md` (hors cache), `reports/strategy_tournament_phase14/` (JSON/CSV/JSONL), `docs/PAPER_TRADING_BOT.md`.

**À exclure :** `.env`, `data/collector_cache/*.json`, `__pycache__/`, `.pytest_cache/`, secrets.

## 8. Garde-fous

- Pas de live trading, pas d’appels Kraken, pas de clés API.
- Pas de merge `master`, pas de deploy.
- `micro_live_candidate` reste OFF.

## 9. Recommandation

**Prêt à commit** sur `phase14/trading-bot-mvp` avec message :  
`feat(bot): add paper trading MVP and strategy tournament`
