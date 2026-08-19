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

## ADR-011 — Séparation entrypoints agent vs recherche

**Contexte :** Deux pipelines coexistent (`src/main.py` vs `src/bot/` + scripts phase) avec des modules homonymes (`portfolio`, `risk`).  
**Décision :** L’agent compétition passe exclusivement par `scripts/dry_run_once.py` / `scripts/run_agent_loop.py` → `src/main.py` → `src/risk.py` + `src/execution.py` + `src/portfolio.py`. La recherche et l’observation forward passent par `scripts/run_*_phase*.py` et `scripts/ops_run_observation_once_phase30.*` → `src/bot/` (+ collectors) sans importer `src/main.py`.  
**Conséquences :** Pas de fusion des modules homonymes ; les tests agent (`tests/test_risk.py`, `tests/test_dry_run_safety.py`) ne couvrent pas le paper engine bot ; l’observation Phase 28–30 écrit sous `reports/paper_observation_phase28/` (gitignored).

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

---

## ADR-012 — Archivage de l'observation forward (2026-08-19)

**Contexte :** Le cron VPS de l'ADR-006 n'a jamais été installé. Trois mois après
la décision `ready_for_vps_cron` (2026-05-21), l'observation compte **1 barre au
2026-05-21 et 0 aujourd'hui** (`reports/PHASE29_OBSERVATION_MONITORING.md`,
healthcheck `FAIL`, `Cron active: False`). L'audit du 2026-08-19 a par ailleurs
établi que le harnais de mesure était défectueux : boucle de replay no-op laissant
le portefeuille standalone vide, donc un baseline qui ne peut jamais vendre ; un
critère de kill sur cinq structurellement inerte ; et un cache funding tronqué à
une page qui neutralisait le leg funding de l'overlay sur ~70 % de la fenêtre de
backtest qui avait fondé son statut `useful_overlay`.

**Décision :** **Ne pas installer le cron.** L'observation forward est archivée.
Les défauts du harnais sont corrigés dans le dépôt — le code fautif ne doit pas
rester en référence publique — mais aucune collecte n'est relancée.

**Alternative écartée :** reprendre l'observation après correction complète
(~6 jours de travail puis 14 jours d'attente) pour observer un overlay de
**risque** qui, même validé, ne génère aucun alpha, sur un compte bloqué au
niveau venue (ADR-003) incapable de l'exécuter. La valeur attendue ne couvre pas
le coût.

**Conséquences :** `reports/PHASE31_REVIEW_CHECKLIST.md` reste comme protocole
non exécuté. Les fichiers d'état d'exécution sous
`reports/paper_observation_phase28/` sont dé-suivis (`git rm --cached`), le
`.gitignore` les visait déjà. `reports/PHASE31_FINAL_VERDICT.md` fait foi.

---

## ADR-013 — La CI est un gate, pas une intention (2026-08-19)

**Contexte :** L'ADR-009 décidait d'ajouter une CI. Elle a été ajoutée mais n'a
**jamais exécuté un seul test** : `ruff` n'était déclaré que dans l'extra `[dev]`
de `pyproject.toml` alors que le workflow installe `requirements.txt`, d'où un
`exit 127` au step lint et tous les steps suivants `skipped`. Les deux seuls runs
de la branche sont rouges. Pendant ces trois mois, un `B018` de ruff signalait la
boucle no-op de l'observation sans que personne ne le voie.

**Décision :** Une CI qui ne peut pas passer est un mensonge, pas une protection.
`ruff` est déclaré dans `requirements.txt` ; les scripts shell d'ops sont couverts
par `bash -n` et `shellcheck -S error` ; et un step `git diff --exit-code` après
pytest interdit qu'un test réécrive un fichier suivi.

**Conséquences :** La CI doit être verte avant tout merge. `master`, la branche
déployée sur Vercel, reçoit le même workflow — elle n'avait aucun répertoire
`.github`.

---

## ADR-014 — Verdict final de la recherche (2026-08-19)

**Contexte :** 30 phases, 872 configurations moteur en OOS, 18 hypothèses
event-study, ~2 600 backtests cumulés sur le même univers (BTC/ETH/SOL, OHLC
Binance + funding/basis/OI), sans correction du budget de tests cumulé.

**Décision :** La recherche d'alpha sur cet univers est **close**, pas en pause.
Résultat : `0 signal tradable`, `0 candidat OOS`. Le seul objet non tué avant
l'audit — l'overlay funding+basis ETH 4h — ne survit pas à l'audit de ses données
d'entrée ni à l'absence de test d'inférence dans le pipeline dérivés.

**Conséquences :** Aucune phase 31 de recherche sur le même univers. Le dépôt
reste public comme démonstration de méthode et résultat négatif documenté. Voir
`reports/PHASE31_FINAL_VERDICT.md`.
