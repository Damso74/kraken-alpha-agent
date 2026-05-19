# QA finale — Phase 3 (Agent 10)

**Date (UTC) :** 2026-05-19  
**Workspace :** `kraken-alpha-agent`  
**Environnement :** Windows 11, PowerShell, `.\.venv\Scripts\Activate.ps1`

---

## 1. Fichiers créés

### Rapports & recherche
| Chemin | Agent / rôle |
|--------|----------------|
| `reports/FINAL_QA_PHASE_3.md` | Agent 10 (ce document) |
| `reports/runtime_smoke/SMOKE_REPORT.md` | Agent 6 |
| `reports/runtime_smoke/*_help*.txt`, `*_cache_*.txt`, `event_study_stablecoins_cache_only.json` | Agent 6 (captures smoke) |
| `reports/research_runs/RUN_LOG.md` | Agent 7 |
| `reports/research_runs/stablecoins_365d.json` | Agent 7 |
| `reports/research_runs/calendar_730d.json` | Agent 7 |
| `reports/research_runs/exchange_status_365d.json` | Agent 7 |
| `reports/research_runs/demo_fng_180d.json` | Agent 7 |
| `reports/ALPHA_RESEARCH_LEADERBOARD.md` | Agent 8/9 |
| `reports/ALPHA_RESEARCH_LEADERBOARD.json` | Agent 8/9 |
| `reports/_build_leaderboard.py` | Agent 8/9 |

### Code source Phase 3
| Chemin | Rôle |
|--------|------|
| `src/data/collectors/` (`_common.py`, `defillama.py`, `etherscan.py`, `status_pages.py`, `wikimedia.py`, `__init__.py`) | Collecteurs read-only |
| `src/signals/` (`stablecoin_supply.py`, `wiki_attention.py`, `calendar_effects.py`, `exchange_status.py`, `eth_gas_congestion.py`, `options_expiry.py`, `btc_mempool.py`, `_stats.py`, `__init__.py`) | Signaux alternatifs |
| `src/research/` (`event_study.py`, `placebo.py`, `__init__.py`) | Harness recherche |
| `scripts/_event_study_common.py` | Utilitaires communs event study |
| `scripts/demo_event_study.py` | Démo F&G |
| `scripts/event_study_calendar.py` | Event study calendrier |
| `scripts/event_study_deribit_expiry.py` | Event study expiry options |
| `scripts/event_study_eth_gas.py` | Event study gas ETH |
| `scripts/event_study_exchange_status.py` | Event study incidents exchange |
| `scripts/event_study_stablecoins.py` | Event study stablecoins |
| `scripts/event_study_wikipedia.py` | Event study Wikipedia |

### Tests
| Chemin |
|--------|
| `tests/test_runtime_smoke_event_study.py` |
| `tests/test_event_study.py` |
| `tests/test_placebo.py` |
| `tests/test_collectors_defillama.py` |
| `tests/test_collectors_etherscan.py` |
| `tests/test_collectors_status_pages.py` |
| `tests/test_collectors_wikimedia.py` |
| `tests/test_signals_calendar_effects.py` |
| `tests/test_signals_eth_gas.py` |
| `tests/test_signals_exchange_status.py` |
| `tests/test_signals_stablecoin_supply.py` |
| `tests/test_signals_wiki_attention.py` |

### Données & documentation
| Chemin |
|--------|
| `data/collector_cache/README.md` |
| `data/collector_cache/defillama.json` |
| `data/collector_cache/status_pages.json` |
| `docs/ALTERNATIVE_ALPHA_PIPELINE.md` |
| `docs/DATA_SOURCES.md` |
| `docs/SIGNAL_REJECTION_POLICY.md` |

---

## 2. Fichiers modifiés

| Fichier | Nature du changement |
|---------|----------------------|
| `.gitignore` | Exclusions cache / artefacts Phase 3 |
| `AGENTS.md` | Mise à jour contexte agents |
| `docs/DEMO_VIDEO_SCRIPT.md` | Mise à jour script démo |

**Non modifié (vérifié) :** `config.yaml` — `git diff HEAD -- config.yaml` → **0 ligne** (profils live `micro_live_100eur`, `micro_live_100eur_crypto`, `xstocks_shadow_36h` inchangés).

---

## 3. Scripts exécutés (référence Agent 7 — `RUN_LOG.md`)

| # | Commande | Exit | JSON produit |
|---|----------|------|--------------|
| 1 | `python scripts/event_study_stablecoins.py --days 365 --output-json reports/research_runs/stablecoins_365d.json` | 0 | Oui |
| 2 | `python scripts/event_study_wikipedia.py --days 365 --output-json reports/research_runs/wikipedia_365d.json` | 2 | Non (403 Wikimedia) |
| 3 | `python scripts/event_study_calendar.py --days 730 --output-json reports/research_runs/calendar_730d.json` | 0 | Oui |
| 4 | `python scripts/event_study_exchange_status.py --days 365 --output-json reports/research_runs/exchange_status_365d.json` | 0 | Oui |
| 5 | `python scripts/event_study_eth_gas.py --days 365 --output-json reports/research_runs/eth_gas_365d.json` | 2 | Non (Etherscan NOTOK) |
| 6 | `python scripts/demo_event_study.py --days 180 --json-out reports/research_runs/demo_fng_180d.json` | 0 | Oui |

**Agent 10 — vérifications complémentaires :**
- `python -m pytest --no-header -q` → **462 tests, 100 % passés**
- `--help` sur les 7 scripts event study + demo → **exit 0** pour tous
- `python -m ruff check` sur fichiers Phase 3 → **134 avertissements style** (non bloquants, voir §5)
- AST import guard → **OK**
- `grep httpx.get tests/` → **0 occurrence**

---

## 4. Tests passés

| Métrique | Résultat |
|----------|----------|
| Total collecté | **462** |
| Passés | **462** |
| Échecs | **0** |
| Durée | ~17 s |
| Échecs corrigés par Agent 10 | **Aucun** (suite déjà verte) |

---

## 5. Linter

| Outil | Résultat |
|-------|----------|
| `ruff` (installé en venv pour QA) | **134 erreurs** sur périmètre Phase 3 |
| `py_compile` (fallback) | OK sur scripts clés |

**Répartition ruff :** UP017 (33), UP045 (31), E402 (27), I001 (16), UP035 (16), F401 (7), B017 (2), B905 (2).

**Verdict linter :** **Non bloquant.** La majorité sont des règles de style modernisation (PEP 604, `datetime.UTC`, imports triés) et E402 attendus dans les scripts avec `sys.path.insert`. Aucun impact runtime ; les tests passent. Pas de correction appliquée (consigne : pas de refactor).

---

## 6. Hypothèses réellement exécutées

| Hypothèse | Période | Événements | Verdict recherche |
|-----------|---------|------------|-------------------|
| Stablecoin supply z≥1.5 → BTC | 365d | 0 | **weak evidence** (hypothèse non exercée) |
| Calendar `weekend_start` → BTC | 730d | 103 | **not supported, move on** |
| Exchange status major+ → BTC | 365d | 2 | **weak evidence** / leaderboard : **not supported** (sous-puissance) |
| Demo F&G < 25 → BTC | 180d | 113 | **weak evidence** (harness démo uniquement) |

**Total exécutions end-to-end avec JSON :** 4/6 tentatives.

---

## 7. Hypothèses bloquées et pourquoi

| Hypothèse | Cause | Documenté dans |
|-----------|-------|----------------|
| Wikipedia attention → BTC | HTTP **403** Wikimedia (User-Agent manquant dans `_common.py`) | `RUN_LOG.md`, leaderboard `blocked` |
| ETH gas congestion → BTC | Etherscan **NOTOK** + **0** lignes dans `etherscan_gas_history.json` | `RUN_LOG.md`, leaderboard `blocked` |

Aucun JSON fabriqué pour ces deux runs — conforme à la politique « no fabricated data ».

---

## 8. Leaderboard généré

| Artefact | Présent |
|----------|---------|
| `reports/ALPHA_RESEARCH_LEADERBOARD.md` | **Oui** |
| `reports/ALPHA_RESEARCH_LEADERBOARD.json` | **Oui** |
| `tradable_count` | **0** (attendu) |
| Runs bloqués intégrés | **Oui** (Wikipedia, ETH gas) |

---

## 9. Risques restants

1. **Collecteurs externes :** Wikimedia exige un User-Agent conforme ; Etherscan nécessite `ETHERSCAN_API_KEY` + historique journalier seedé.
2. **Stablecoins :** z=1.5 / direction=high → 0 événements sur 365j ; paramètres à recalibrer avant toute conclusion.
3. **Exchange status :** n=2 incidents → inférence impossible ; verdict « weak » script vs « not supported » leaderboard (politique stricte Agent 8).
4. **Demo F&G :** 2 cellules BH rejetées mais verdict **weak evidence** — risque de sur-interprétation si le demo est confondu avec le harness principal.
5. **Réseau dans scripts (hors tests) :** les event studies appellent Kraken OHLC en live ; `--use-cache-only` partiel sur certains scripts (documenté dans `SMOKE_REPORT.md`).
6. **Linter :** 134 issues ruff non corrigées — dette style, pas de régression fonctionnelle observée.
7. **Mots sensibles dans `reports/` :** occurrences de *tradable*, *live-ready*, *profitable* uniquement dans des **déclarations de politique** (« 0 signal tradable », « jamais marqué profitable ») — **contexte non trompeur**.

---

## 10. Recommandation

### **merge**

**Justification :**
- `config.yaml` et profils live **inchangés**
- **462/462** tests pytest verts
- Aucun `httpx.get` dans `tests/`
- Isolation recherche OK (pas d'import `execution` / `risk` / `futures_kraken_cli` depuis `data`/`signals`/`research`)
- Livrables Phase 3 présents : smoke report, RUN_LOG, 4 JSON recherche, leaderboard, docs cache
- Blocages Wikipedia / Etherscan **documentés**, pas contournés
- Aucun signal marqué tradable ou live-ready

**Actions post-merge (non bloquantes) :**
1. Ajouter User-Agent Wikimedia dans `src/data/collectors/_common.py` puis re-run Wikipedia.
2. Seeder `etherscan_gas_history.json` avec clé API valide.
3. Optionnel : `ruff check --fix` sur périmètre Phase 3 dans une PR dédiée style.

---

*Agent 10 — gate QA Phase 3. Aucune modification de code bloquante requise.*
