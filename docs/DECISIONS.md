# Décisions architecturales (ADR light)

Décisions enregistrées à partir de l’état du dépôt et de `AGENTS.md`. Format : contexte → décision → conséquences.

---

## ADR-001 — Triple opt-in live

**Contexte :** Agent hackathon ; risque d’ordre accidentel.  
**Décision :** Live exige `TRADING_MODE=live` + `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true`, re-validé à chaque cycle dans `src/risk.py`.  
**Conséquences :** Tests exhaustifs des combinaisons partielles ; jamais persister les flags live dans `.env` commité.

---

## ADR-002 — Dual portfolio (live vs paper research)

**Contexte :** Agent xStocks utilise SQLite ; backtests bot utilisent structures in-memory.  
**Décision :** Deux modules : `src/portfolio.py` (live/dry) et `src/bot/portfolio.py` (`PaperPortfolio`).  
**Conséquences :** Les strategies dans `src/strategies/` importent `PaperPortfolio` pour backtest ; l’agent live utilise `src/portfolio`. Documenté dans `docs/PAPER_TRADING_BOT.md`.

---

## ADR-003 — PEDSL-CY et blocage xStocks spot

**Contexte :** Compte EU Chypre ; API spot xStocks retourne `EGeneral:Permission denied`.  
**Décision :** Documenter honnêtement ; dashboard `web/` affiche erreurs verbatim ; pas de claim « live xStocks ».  
**Conséquences :** PnL soumission = backtest statique JSON ; observation forward sur overlay Binance public.

---

## ADR-004 — Futures 1× override (2026-05-15)

**Contexte :** Seule voie perps xStocks disponible sur certaines entités.  
**Décision :** Profil `micro_live_100eur` → `execution.engine: futures` avec `HARDCODED_MAX_LEVERAGE = 1.0`, SELL exit-only, funding gate, pas de transfer wallet.  
**Conséquences :** Overrides conscients dans `AGENTS.md` ; profil default `aggressive_competition` reste spot.

---

## ADR-005 — Pipeline recherche : 0 paper_candidate price-only

**Contexte :** Phases 16–25 — exhaustive backtests OHLCV.  
**Décision :** Pas d’alpha price-only à frais nuls ; regime router = overlay pas alpha.  
**Conséquences :** Track actif = ETH 4h funding+basis overlay ; forward observation Phase 28–30.

---

## ADR-006 — Observation forward ops (Phase 30)

**Contexte :** Besoin d’observation 2–4 semaines avant micro-live.  
**Décision :** Cron VPS 4 h via `ops_run_observation_once_phase30.*` ; cockpit statique sous `reports/` (pas `web/`).  
**Conséquences :** Flag `STOP_OBSERVATION` ; `--cache-only` sans refresh = cache stale ; pas de dev produit jusqu’à fin observation.

---

## ADR-007 — Branche master frozen

**Contexte :** Hackathon payment/validation pending.  
**Décision :** Pas de merge feature branches → `master` jusqu’à validation.  
**Conséquences :** Travail sur branches `phase*/` ; push feature OK.

---

## ADR-008 — Anti-curve-fit walk-forward

**Contexte :** Tentations d’optimiser métriques backtest.  
**Décision :** Filtre OOS strict ; fenêtre 30 j récente toujours en TEST ; échec OOS → doc honnête dans `METHODOLOGY.md`.  
**Conséquences :** `scripts/walk_forward_*.py` et tests associés.

---

## ADR-009 — Pas de CI avant audit 2026-05-21

**Contexte :** Validation manuelle uniquement.  
**Décision (audit) :** Ajouter CI pytest-only mock transport.  
**Conséquences :** `.github/workflows/ci.yml` — pas de deploy, pas de secrets.

---

## ADR-010 — Signaux sans collector (btc_mempool)

**Contexte :** Signal implémenté, feed Mempool.space absent.  
**Décision :** Conserver code + backlog ; classer `blocked_data` dans decision board.  
**Conséquences :** Pas de suppression ; pas de tests tant que collector absent.
