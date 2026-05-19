# QA finale — Phases 4 à 10 (Agents 11–22)

**Date (UTC) :** 2026-05-19  
**Agent :** 23 — Orchestrateur / QA finale  
**Workspace :** `kraken-alpha-agent`  
**Branche :** `master` (à jour avec `origin/master`)  
**Environnement :** Windows 11, PowerShell, `.\.venv\Scripts\Activate.ps1`

---

## 1. Résumé exécutif

Les phases 4–10 livrent un **pipeline alpha alternatif read-only** cohérent : collecteurs (`src/data/`), signaux (`src/signals/`), recherche (`src/research/`), scripts `event_study_*.py`, documentation, rapports V2 et leaderboard Phase 6.

| Contrôle | Résultat |
|----------|----------|
| `config.yaml` inchangé | **OK** (diff vide) |
| Profils live inchangés / aucun nouveau profil live | **OK** |
| Secrets dans le diff | **OK** (seul `.gitignore` modifié côté git) |
| Caches volumineux commités | **OK** (`data/collector_cache/` non suivi + règle `.gitignore`) |
| Pytest complet | **576 passés**, 0 échec (après correctif minimal ETH gas) |
| Ruff (périmètre phases) | **328 avertissements** (style, non bloquant CI implicite) |
| AST isolation recherche | **OK** (0 import `execution` / `risk` / `futures_kraken_cli`) |
| Leaderboard V2 | **OK** — `tradable_count: 0`, `oos_candidate_count: 0` |
| Stablecoins 0 events | **OK en V2** (`blocked: insufficient events`) |
| Wikipedia | **Débloqué** (16 events, `weak evidence`) |
| ETH gas | **Bloqué** (historique absent, documenté) |
| Paper design | **OK** — pas de câblage live |

**Correctif appliqué pendant la QA :** `scripts/event_study_eth_gas.py` émet désormais le message canonique `blocked: missing historical gas cache` en mode `--use-cache-only` sans historique (test bloquant).

**Dette mineure avant merge :** l’artefact Phase 3 `reports/research_runs/stablecoins_365d.json` affiche encore `weak evidence` pour 0 events (obsolète ; V2 est correcte).

**Recommandation :** **merge after tiny fixes** — committer le lot phases 4–10 + `.gitignore`, supprimer ou régénérer l’artefact stablecoins Phase 3 obsolète, ne pas toucher `config.yaml`.

---

## 2. Fichiers créés (non suivis git — inventaire principal)

### Code

| Chemin | Rôle |
|--------|------|
| `src/data/collectors/_common.py` | Helpers cache HTTP read-only |
| `src/data/collectors/binance_public.py` | OHLC public paginé |
| `src/data/collectors/defillama.py` | Supply stablecoins / TVL |
| `src/data/collectors/etherscan.py` | Oracle gas + historique |
| `src/data/collectors/status_pages.py` | Incidents exchanges |
| `src/data/collectors/wikimedia.py` | Pageviews Wikipedia |
| `src/signals/*.py` | Builders d’événements (calendar, stablecoin, wiki, gas, status, …) |
| `src/research/cost_model.py` | Frais pessimistes recherche |
| `src/research/tradeability.py` | Overlay économique leaderboard |
| `src/research/regime_analysis.py` | Robustesse par régime |
| `src/research/concentration.py` | Risque de concentration |
| `src/research/paper_simulator.py` | Arithmétique paper-only Phase 10 |

### Scripts

| Chemin |
|--------|
| `scripts/_event_study_common.py` |
| `scripts/demo_event_study.py` |
| `scripts/event_study_calendar.py` |
| `scripts/event_study_deribit_expiry.py` |
| `scripts/event_study_eth_gas.py` |
| `scripts/event_study_exchange_status.py` |
| `scripts/event_study_stablecoins.py` |
| `scripts/event_study_wikipedia.py` |

### Tests (22 fichiers)

`tests/test_collectors_*.py`, `tests/test_event_study.py`, `tests/test_signals_*.py`, `tests/test_research_cost_model.py`, `tests/test_regime_analysis.py`, `tests/test_concentration.py`, `tests/test_tradeability.py`, `tests/test_leaderboard_tradeability.py`, `tests/test_paper_simulator.py`, `tests/test_placebo.py`, `tests/test_runtime_smoke_event_study.py`, etc.

### Documentation

| Fichier |
|---------|
| `docs/ALTERNATIVE_ALPHA_PIPELINE.md` |
| `docs/DATA_SOURCES.md` |
| `docs/HYPOTHESIS_BACKLOG_PHASE_9.md` |
| `docs/NEXT_5_HYPOTHESES.md` |
| `docs/PAPER_OBSERVATION_DESIGN.md` |
| `docs/SIGNAL_REJECTION_POLICY.md` |
| `docs/WEIRD_BUT_TESTABLE_SIGNALS.md` |

### Rapports

| Fichier |
|---------|
| `reports/ALPHA_RESEARCH_LEADERBOARD_V2.md` / `.json` |
| `reports/ALPHA_RESEARCH_LEADERBOARD.md` / `.json` (Phase 3, conservés) |
| `reports/ECONOMIC_REALISM.md` |
| `reports/REGIME_ROBUSTNESS.md` |
| `reports/CONCENTRATION_RISK.md` |
| `reports/PHASE_3_VS_PHASE_6.md` |
| `reports/_build_leaderboard.py` |
| `reports/research_runs_v2/*` (JSON + `RUN_LOG_V2.md`) |
| `reports/research_runs/*` (Phase 3 — partiellement obsolète) |
| `reports/runtime_smoke/*` |

### Données locales (gitignored)

`data/collector_cache/` (OHLC Binance, caches API) — **non à committer**.

---

## 3. Fichiers modifiés

| Fichier | Nature du changement |
|---------|----------------------|
| `.gitignore` | Ignore `data/collector_cache/*` sauf README + `examples/` |
| `scripts/event_study_eth_gas.py` | **Correctif QA** : message `BLOCKED_MISSING_GAS_HISTORY` sur cache vide |

**Non modifié (exigence respectée) :** `config.yaml`, profils `micro_live_*` dans le dépôt suivi.

---

## 4. Tests

```text
576 tests collected
576 passed, 0 failed
Durée ~20 s (suite complète, post-correctif)
```

| Avant correctif | Après |
|-----------------|-------|
| 1 échec : `test_event_study_eth_gas_cache_only_blocked_message` | 0 échec |

Le test exige la sous-chaîne `blocked: missing historical gas cache` dans stderr ; le script n’émettait qu’un message `FATAL use_cache_only but no gas history at …`.

---

## 5. Linter (Ruff)

| Périmètre | Erreurs | Bloquant ? |
|-----------|---------|------------|
| Repo entier (`ruff check .`) | 519 | Non (style / imports) |
| Phases 4–10 (`src/data`, `src/signals`, `src/research`, `scripts`, `tests` ciblés) | 328 | Non |

Principales règles : `UP017`, `UP045`, `E402`, `F401`, `I001` — **273 auto-fixables** avec `--fix`.

**Verdict linter :** avertissements documentés ; **aucun bloquant fonctionnel** identifié pour la QA phases 4–10. Si la CI impose `ruff check .` sans exclusion, prévoir un passage `--fix` ou un périmètre restreint avant merge.

---

## 6. Scripts exécutés

### Contrôles git / hygiène

- `git status` — branche `master`, travail non commité (fichiers non suivis + `.gitignore`)
- `git diff --name-only` — **uniquement** `.gitignore`
- `git diff config.yaml` — **vide**

### Pytest

- `pytest --no-header -q` → 576 OK

### Ruff

- `ruff check .` et `ruff check src/data src/signals src/research scripts tests`

### `--help` event studies + demo

Tous retournent un usage argparse valide (exit 0) :

- `scripts/demo_event_study.py`
- `scripts/event_study_calendar.py`
- `scripts/event_study_deribit_expiry.py`
- `scripts/event_study_eth_gas.py`
- `scripts/event_study_exchange_status.py`
- `scripts/event_study_stablecoins.py`
- `scripts/event_study_wikipedia.py`

### AST isolation

Script Python : parcours `src/data`, `src/signals`, `src/research` — **0 violation** d’import `execution`, `risk`, `futures_kraken_cli`.

---

## 7. Hypothèses exécutées (research runs V2)

Source : `reports/research_runs_v2/RUN_LOG_V2.md`, artefacts JSON, `ALPHA_RESEARCH_LEADERBOARD_V2.json`.

| Signal | Events | BH rej | Verdict recherche |
|--------|--------|--------|-------------------|
| `stablecoin_supply_z_high` | 0 | — | **blocked** |
| `wikipedia_btc_attention` | 16 | 0/5 | **weak evidence** |
| `calendar_weekend_start` | 105 | 0/5 | **not supported, move on** |
| `exchange_status_major_incident` | 2 | 0/5 | **weak evidence** (sous-puissant) |
| `demo_fear_greed_extreme_fear` | 129 | 2/5 | **weak evidence** (demo only) |
| `eth_gas_congestion` | — | — | **skipped / blocked** |

---

## 8. Hypothèses bloquées

| Hypothèse | Raison |
|-----------|--------|
| **ETH gas congestion** | Pas de `data/collector_cache/etherscan_gas_history.json` (≥181 lignes requises). Verdict leaderboard : `blocked`. Unblock : `ETHERSCAN_API_KEY` + append journalier. |
| **Stablecoin supply (z≥1.5)** | 0 événements alignés sur 365j — `blocked: insufficient events` (V2). |

---

## 9. Signaux rejetés

| Signal | Verdict final (overlay économique) |
|--------|----------------------------------|
| `calendar_weekend_start` | `not supported, move on` + rejet économique (gross < seuil suspect) |
| `wikipedia_btc_attention` | `weak evidence` + `economically impossible` |
| `exchange_status_major_incident` | `weak evidence` + sous-puissance + rejet économique |
| `demo_fear_greed_extreme_fear` | `weak evidence` (demo, turnover > 30 %) |
| `stablecoin_supply_z_high` | `blocked` + `economic_reject` |

**Aucun signal promu vers OOS ou live.**

---

## 10. Weak evidence

| Signal | Justification |
|--------|---------------|
| Wikipedia | 16 events, raw p≈0.02 sur vol post_3, **BH 0/5** |
| Exchange status | 2 events (< 5), BH 0/5 |
| Demo F&G | BH 2/5 sur vol uniquement ; harness demo, retour non supporté |

**Note Phase 3 :** `reports/research_runs/stablecoins_365d.json` indique encore `weak evidence` avec `events_count: 0` — **artefact obsolète** (avant `compute_verdict` « blocked »). Ne pas utiliser pour décision ; V2 est la référence.

---

## 11. Candidats OOS (attendu ~0)

```json
"oos_candidate_count": 0
```

Confirmé dans `ALPHA_RESEARCH_LEADERBOARD_V2.json`. Aucune ligne avec verdict `candidate for OOS retest`.

---

## 12. Risques restants

1. **Artefacts Phase 3** (`reports/research_runs/`) — verdicts « weak evidence » sur 0 events ; risque de lecture trompeuse si non archivés.
2. **Ruff** — dette style sur le périmètre ajouté (328 erreurs ciblées).
3. **ETH gas** — recherche impossible sans seed d’historique ; pas de régression code, dette data.
4. **Stablecoins** — seuil z=1.5 ne déclenche rien ; exploration z=1.0 documentée mais non pré-enregistrée.
5. **Demo F&G** — encore sur OHLC Kraken dans le harness demo (hors scope fix minimal).
6. **Travail non commité** — tout le lot phases 4–10 est encore untracked ; merge nécessite `git add` sélectif (exclure `data/collector_cache/`).

---

## 13. Dettes data

| Source | État | Action |
|--------|------|--------|
| `etherscan_gas_history.json` | Absent | Seed / append quotidien |
| DefiLlama / Wikimedia / status | Cache local OK en run V2 | Maintenir gitignore |
| Binance OHLC BTC | Cache `ohlc_daily_BTC.json` | Local uniquement |
| Stablecoins z≥1.5 | 0 events | Revoir seuil ou fenêtre si hypothèse maintenue |

---

## 14. Recommandation

### **merge after tiny fixes**

**Prêt :**

- Tests 576/576 verts
- `config.yaml` et profils live intacts
- Politique « 0 tradable / 0 OOS » respectée dans V2
- Isolation AST recherche / exécution
- Documentation alignée (`DATA_SOURCES.md`, `PAPER_OBSERVATION_DESIGN.md`, backlog Phase 9)
- Stablecoins 0 events → **blocked** en V2

**Avant merge (tiny fixes) :**

1. Committer `.gitignore` + arborescence phases 4–10 **sans** `data/collector_cache/` (sauf README/examples).
2. Supprimer ou régénérer `reports/research_runs/stablecoins_365d.json` (verdict obsolète).
3. Inclure le correctif `event_study_eth_gas.py` (message blocked canonique).
4. (Optionnel) `ruff check --fix` sur le périmètre neuf si la CI est stricte.

**Ne pas faire :**

- Modifier `config.yaml`
- Ajouter un profil live
- Promouvoir un signal vers le moteur de trading

---

## Annexe — Checklist numérotée (requête Agent 23)

| # | Contrôle | Statut |
|---|----------|--------|
| 1 | `git status` && `git diff --name-only` | OK — seul `.gitignore` modifié (suivi) |
| 2 | `config.yaml` diff vide | OK |
| 3 | Profils live inchangés | OK (aucun diff `config.yaml`) |
| 4 | Pas de nouveau profil live | OK |
| 5 | Pas de secrets dans le diff | OK |
| 6 | Pas de gros caches commités | OK (gitignore + untracked) |
| 7 | Pytest 576/576 | OK (1 correctif minimal) |
| 8 | Ruff | 328 warnings périmètre phases — non bloquant |
| 9 | `--help` tous `event_study_*.py` + demo | OK |
| 10 | Pas de `httpx.get` nu dans `tests/` | OK — uniquement `@patch(...httpx.get)` |
| 11 | AST data/signals/research | OK — 0 import interdit |
| 12 | Docs ↔ code | OK (collecteurs, gates, paper) |
| 13 | Rapports sans claim tradable positive | OK — mentions = politique « 0 » |
| 14 | Stablecoins 0 events → blocked | OK V2 ; **FAIL** artefact Phase 3 |
| 15 | Wikipedia débloqué ou documenté | OK — 16 events, collector UA |
| 16 | ETH gas blocked ou historique | OK — blocked + RUN_LOG |
| 17 | Leaderboard V2 existe | OK |
| 18 | Réalisme économique | OK — `ECONOMIC_REALISM.md`, `cost_model.py` |
| 19 | Robustesse régime | OK — `regime_analysis.py`, `REGIME_ROBUSTNESS.md` |
| 20 | Backlog hypothèses | OK — `HYPOTHESIS_BACKLOG_PHASE_9.md` |
| 21 | Paper design sans live | OK — `paper_simulator.py`, design doc |

---

*Rapport généré par l’agent QA 23 — Phases 4–10.*
