# QA finale — Phase 11 (Agent 34)

**Date (UTC) :** 2026-05-19  
**Agent :** 34 — QA finale Phase 11  
**Workspace :** `kraken-alpha-agent`  
**Branche :** `posthackathon/research-lab-phase-3-10`  
**Environnement :** Windows 11, PowerShell, `.\.venv\Scripts\Activate.ps1`, `$env:PYTHONIOENCODING='utf-8'`  
**Contraintes respectées :** aucun merge `master` / `main`, aucun déploiement.

---

## 1. Résumé exécutif

La Phase 11 (Agents 27–33) livre un sprint recherche **read-only** cohérent : 8 artefacts JSON sous `reports/research_runs_phase11/`, leaderboard Phase 11, comparaison Phase 6, red team adversarial, et extension du pipeline (collecteurs, signaux, scripts `event_study_*`, tests).

| Contrôle | Résultat |
|----------|----------|
| `git status` / diff noms | Branche correcte ; **1 fichier suivi modifié** (`.gitignore`) ; **gros lot non suivi** (code Phase 11, `reports/`, `data/collector_cache/`) |
| `config.yaml` inchangé | **OK** (`git diff origin/master -- config.yaml` vide) |
| Profils live inchangés / aucun nouveau profil live | **OK** (`aggressive_competition` actif, `micro_live_100eur` + `micro_live_100eur_crypto` inchangés) |
| Secrets / caches volumineux commités | **OK** — pas de secrets dans le diff ; `data/collector_cache/` ~1 Mo, 8 fichiers, **gitignored** |
| Pytest complet (`--no-header -q`) | **618 collectés, 618 passés**, 0 échec (via `.venv` uniquement) |
| Ruff | **575** erreurs repo entier ; **295** sur périmètre phases 4–11 — **avertissements style, non bloquants** |
| Scripts `event_study_*` `--help` | **OK** (usage argparse valide sur les 8 scripts) |
| `httpx.get` dans les tests | **OK** — uniquement sous `@patch` (`test_collectors_wikimedia.py`) |
| AST isolation `data` / `signals` / `research` | **OK** — **0** import `execution` / `risk` / `futures_kraken_cli` |
| Claims interdites dans les rapports Phase 11 | **OK** — `tradable_count: 0` ; pas de signal marqué live-ready/profitable |
| Stablecoins 0 événements ≠ weak evidence | **OK** — `P9-SC-001-PR-30d-high` → `blocked` (JSON + leaderboard) |
| Données bloquées documentées | **OK** — RUN_LOG Phase 11, variantes volume 0 evt, exchange n=1, ETH gas (hérité Phase 4–10) |
| `RED_TEAM_PHASE11.md` | **Présent** |
| `ALPHA_RESEARCH_LEADERBOARD_PHASE11` | **Présent** (`.md` + `.json`) |
| Merge `master` / `main` | **Non** — `HEAD` = `origin/master` (`58ac5fe`), **0 commit** d’avance ; travail Phase 11 **non commité** |
| Déploiement | **Aucun** |

### Réconciliation leaderboard ↔ red team (obligatoire)

| Source | Candidats OOS déclarés | Verdict QA |
|--------|------------------------|------------|
| `ALPHA_RESEARCH_LEADERBOARD_PHASE11.json` | **`oos_candidate_count: 2`** (`wikipedia_crypto_basket_z1.5`, `z2.0`) | **Révoqués** par red team |
| `RED_TEAM_PHASE11.md` | **0 sprint survivant** ; Wikipedia → **FAIL**, interdiction « candidate OOS » | **Fait référence** pour décision |

**Position QA :** après red team, **0 candidat OOS** ne doit être promu. Les deux lignes Wikipedia du leaderboard Phase 11 sont des **artefacts de script** (`compute_phase11_verdict` trop laxiste), pas des promotions validées. Aligner le leaderboard et `PHASE_6_VS_PHASE11.md` (§ synthèse « seuls candidats OOS ») sur le red team avant tout merge.

**Correctifs bloquants appliqués pendant cette QA :** **aucun** (suite verte sous `.venv`).

**Recommandation :** **keep on posthackathon branch** — committer le bundle Phase 11 + rétrograder les 2 candidats Wikipedia au verdict red team (`kill` ou `weak evidence` max, `oos_candidate_count: 0`) avant toute fusion vers `master` ou jugement externe.

---

## 2. Fichiers créés / modifiés

### Suivi git (état au moment de la QA)

| Statut | Chemins principaux |
|--------|-------------------|
| **Modifié (suivi)** | `.gitignore` — exclusion `data/collector_cache/*` (sauf README / examples) |
| **Non suivi (Phase 11 + dette phases 4–10 non commitée)** | `src/data/`, `src/signals/`, `src/research/`, `scripts/event_study_*.py`, `scripts/_event_study_common.py`, `scripts/demo_event_study.py`, `tests/test_*` (collectors, signals, event study, research), `docs/*.md` (pipeline, sources, backlog), `reports/**` (leaderboards, red team, `research_runs_phase11/`, `_build_leaderboard.py`, etc.) |
| **Cache local (gitignored)** | `data/collector_cache/` (~1 Mo) |

### Artefacts Phase 11 (agents 27–33)

| Fichier | Rôle |
|---------|------|
| `reports/research_runs_phase11/*.json` (8 fichiers) | Résultats calendrier, stablecoins ×4, volume, Wikipedia, exchange status |
| `reports/research_runs_phase11/RUN_LOG_PHASE11.md` | Journal d’exécution |
| `reports/ALPHA_RESEARCH_LEADERBOARD_PHASE11.md` / `.json` | Leaderboard agrégé (Agent 33) |
| `reports/RED_TEAM_PHASE11.md` | Revue adversarial (Agent 32) |
| `reports/PHASE_6_VS_PHASE11.md` | Comparaison archiviste |
| `reports/FINAL_QA_PHASE11.md` | Ce document (Agent 34) |

**Non modifié (exigence) :** `config.yaml`, profils live dans le dépôt suivi.

---

## 3. Tests

```text
618 tests collected
618 passed, 0 failed
Durée ~14–15 s (suite complète, .venv)
```

**Note environnement :** sans `.venv`, 25 erreurs de collection (`ModuleNotFoundError: pydantic_settings`). La QA et la CI doivent activer `.\.venv\Scripts\Activate.ps1` (ou équivalent).

Tests Phase 11 couverts notamment : `test_event_study_exchange_status_phase11.py`, `test_signals_*`, `test_collectors_*`, `test_runtime_smoke_event_study.py`, `test_leaderboard_tradeability.py`, etc.

---

## 4. Linter (Ruff)

| Périmètre | Erreurs | Bloquant ? |
|-----------|---------|------------|
| Repo entier (`ruff check .`) | **575** | Non (style / imports ; 497 auto-fixables) |
| Phases 4–11 (`src/data`, `src/signals`, `src/research`, scripts event study, tests associés) | **295** | Non (224 auto-fixables) |

Règles fréquentes : `E402`, `F401`, `F841`, `UP017`, `I001`. Aucune erreur bloquant l’exécution des harness ou la politique recherche identifiée.

---

## 5. Scripts (`--help`)

Tous les scripts event study listés produisent un usage argparse valide :

| Script | Statut `--help` |
|--------|-----------------|
| `scripts/event_study_calendar.py` | OK |
| `scripts/event_study_deribit_expiry.py` | OK |
| `scripts/event_study_eth_gas.py` | OK |
| `scripts/event_study_exchange_status.py` | OK |
| `scripts/event_study_stablecoins.py` | OK |
| `scripts/event_study_volume_shock.py` | OK |
| `scripts/event_study_wikipedia.py` | OK |
| `scripts/demo_event_study.py` | OK |

Confirmé aussi par `tests/test_runtime_smoke_event_study.py` (exit code 0).

---

## 6. Hypothèses exécutées / bloquées

### Exécutées (sprint Phase 11)

| Sprint | Hypothèses / variantes | Artefact | Verdict pipeline | Verdict red team |
|--------|------------------------|----------|------------------|------------------|
| Calendrier | 5 micro-baselines | `calendar_micro_baselines.json` | weak evidence | **FAIL** (dup Sunday/Monday) |
| Stablecoins | P9-SC-001-PR ×4 | `p9-sc-001-pr-*.json` | weak / blocked | **FAIL** |
| Volume | P9-MS-023 ×4 | `volume_shock_all_365d.json` | weak / blocked | **FAIL** (z-high → kill recommandé) |
| Wikipedia | panier z1.5 / z2.0 | `wikipedia_basket_365d.json` | **candidate OOS** ×2 | **FAIL — révoquer OOS** |
| Exchange status | 9 variantes | `exchange_status_deep_dive_365d.json` | kill / blocked | **FAIL** (confirme kill) |

### Bloquées (documentées)

| Hypothèse | Raison | Où documenté |
|-----------|--------|--------------|
| `P9-SC-001-PR-30d-high` | 0 événements (expansion z≥+1,0 absente) | JSON `blocked: insufficient events`, leaderboard **blocked** |
| Volume `vol_z20_range_compression` / `vol_z20_low_abs_return` | 0 événements | RUN_LOG_PHASE11, leaderboard **blocked** |
| Exchange `scheduled_maintenance`, `impact_major`, `impact_critical` | n=1 | leaderboard **blocked** |
| ETH gas congestion | Pas d’historique cache (Phase 4–10) | V2 / `RUN_LOG_V2.md` — non re-run Phase 11 |

---

## 7. Signaux rejetés

| Signal / famille | Verdict final (post red team) |
|------------------|-------------------------------|
| Calendrier (tous effets) | **kill** ou recherche descriptive seule (`us_market_open` → WARNING max) |
| Stablecoins (seuils avec events) | **kill** (placebos shift/lag survivent) |
| Volume shock z-high | **kill** (placebos post_3 à p=1, return négatif) |
| Wikipedia panier z1.5 / z2.0 | **kill** (pas d’OOS, concentration temporelle, return NS) |
| Exchange status (toutes variantes) | **kill** / **blocked** |

**Aucun signal tradable, live-ready, ou allouable en capital OOS.**

---

## 8. Weak evidence

| Signal | Justification | Note red team |
|--------|---------------|---------------|
| Calendrier `us_market_open_window` | BH vol/volume, pas return ; coûts / turnover | WARNING max, pas OOS |
| Stablecoins 30d-low / 7d-high / 7d-low | BH partiel, `placebo_pass: false` | Ne pas traiter comme weak — **kill** |
| Volume z20/z60 high | BH post_7, placebos shift/shuffle échouent | Rétrograder vers **kill** |
| Calendrier Sunday / Monday | BH apparent sur Monday | **FAIL** — échantillon dupliqué |

**Stablecoins 30d-high (0 evt) :** verdict **`blocked`**, jamais **`weak evidence`** — conforme à la politique Phase 3/6.

---

## 9. Candidats OOS (réconciliation)

| Couche | Compte | Détail |
|--------|--------|--------|
| Leaderboard Phase 11 (brut) | **2** | `wikipedia_crypto_basket_z1.5`, `wikipedia_crypto_basket_z2.0` |
| Red team Phase 11 | **0** | Révocation explicite ; pas de partition hold-out |
| **Verdict QA final** | **0** | Ne pas utiliser le leaderboard Phase 11 pour allouer une file OOS sans rebuild + override red team |

Actions recommandées avant merge :

1. Rebuild `python reports/_build_leaderboard.py --phase11` avec règles alignées red team (pas de « candidate » sans hold-out + placebos bootstrap + overlay return).
2. Mettre à jour `PHASE_6_VS_PHASE11.md` § synthèse (ne plus lister Wikipedia comme « seuls candidats OOS »).
3. Propager `phase11_final_verdict` dans `wikipedia_basket_365d.json` si les artefacts sont versionnés.

---

## 10. Risques

1. **Travail non commité** sur une branche dont la pointe = `master` — risque de perte ou de confusion au jugement hackathon.
2. **Contradiction narrative** leaderboard (2 OOS) vs red team (0) vs `ALPHA_RESEARCH_LEADERBOARD_V2.md` (0 OOS Phase 6 wiki).
3. **Placebo exchange status** — champ `random_timestamps` invalide (recopie primaire) ; toute robustesse dérivée est fausse.
4. **OHLC hétérogènes** — cache Kraken/Binance selon les sprints ; reproductibilité externe non prouvée.
5. **Ruff** — dette style sur le périmètre ajouté (295–575 erreurs).
6. **Pytest hors venv** — échec de collection si dépendances manquantes.

---

## 11. Dettes data

| Dette | Impact | Déblocage |
|-------|--------|-----------|
| `data/collector_cache/` non versionné | Reproductibilité locale seulement | Publier hash + procédure fetch ; caches exemples sous `examples/` |
| ETH gas history absent | Harness gas en **blocked** | `ETHERSCAN_API_KEY` + historique ≥181 jours |
| DefiLlama publication lag | Alignement supply/OHLC incertain | Documenter lag dans JSON |
| Wikipedia concentration (août 2025) | BH potentiellement régime-local | Leave-one-month-out obligatoire |
| Duplication calendrier Sunday ≡ Monday (daily UTC) | Deux pré-enregistrements, un signal | Granularité horaire ou retrait d’un effet |

---

## 12. Contrôles git / merge / deploy

```text
Branche : posthackathon/research-lab-phase-3-10
HEAD     : 58ac5fe (identique à origin/master)
Commits ahead of master : 0
git diff --name-only (suivi) : .gitignore
Merge master into branch : NON (branche déjà à la pointe master ; pas de merge commit)
Deploy : NON
```

---

## 13. Recommandation

| Option | Applicable ? |
|--------|--------------|
| **keep on posthackathon branch** | **Oui — recommandé** : committer le lot Phase 11, aligner leaderboard sur red team (`oos_candidate_count: 0`), conserver hors `master` jusqu’au jugement. |
| merge after judging | Possible après commit + réconciliation OOS + revue humaine. |
| merge after tiny fixes | Si seuls correctifs narratifs (leaderboard, PHASE_6_VS_PHASE11) + `ruff --fix` ciblé. |
| rollback partial | Non requis — pas de régression tests ; pas de changement `config.yaml`. |
| do not merge | Trop strict : le code et les tests sont sains ; le blocage est **gouvernance des verdicts**, pas qualité CI. |

**Synthèse une ligne :** pipeline Phase 11 **techniquement prêt** sur la branche post-hackathon ; **scientifiquement 0 OOS** après red team — ne pas fusionner vers `master` tant que les 2 candidats Wikipedia ne sont pas révoqués dans les artefacts publiés.

---

## Références

- `reports/RED_TEAM_PHASE11.md`
- `reports/ALPHA_RESEARCH_LEADERBOARD_PHASE11.md` / `.json`
- `reports/research_runs_phase11/RUN_LOG_PHASE11.md`
- `reports/PHASE_6_VS_PHASE11.md`
- `reports/FINAL_QA_PHASE_4_10.md` (contrôles transverses phases 4–10)
- `docs/SIGNAL_REJECTION_POLICY.md`

**Disclaimer QA :** ce rapport ne valide aucune rentabilité, aucun déploiement live, aucune modification de `config.yaml`. Phase 11 reste **research-only**.

---

## 14. Addendum — réconciliation leaderboard (2026-05-19)

| Item | Statut |
|------|--------|
| Rebuild `python reports/_build_leaderboard.py --phase11` | **Fait** |
| `oos_candidate_count` dans `ALPHA_RESEARCH_LEADERBOARD_PHASE11.json` | **0** |
| Wikipedia z1.5 / z2.0 | **weak evidence** + `revoked_by_red_team` ; red team `revoked` |
| Règle builder | `fail` / `revoked` → pas de `candidate for further OOS testing` |
| `PHASE_6_VS_PHASE11.md` | Synthèse alignée (**0 OOS**) |
| Note détaillée | `reports/PHASE11_RECONCILIATION_NOTE.md` |

**Position QA mise à jour :** la contradiction leaderboard (2 OOS) vs red team (0) est **levée**. Merge `master` et deploy restent **hors périmètre** ; branche post-hackathon prête pour commit.
