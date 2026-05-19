# Merge hygiene — Phases 4 à 10

**Date (UTC) :** 2026-05-19  
**Agent :** 25 — merge hygiene final (post Phases 4–10)  
**Workspace :** `kraken-alpha-agent`  
**Branche de travail :** `posthackathon/research-lab-phase-3-10` (Agent 24 ; `posthackathon` seul est bloqué par ce nom de branche imbriqué)  
**`HACKATHON_FREEZE_NOTE.md` :** absent du dépôt — ne pas merger vers `master` avant jugement hackathon.

---

## 1. Décision merge

### **→ PRÊT À COMMITTER sur `posthackathon/research-lab-phase-3-10` — NE PAS merger `master` avant jugement**

Motifs :

1. Périmètre phases 4–10 identifié ; `.gitignore` couvre les caches collecteurs.
2. Artefact Phase 3 `stablecoins_365d.json` aligné sur `blocked: insufficient events` (0 events).
3. V2 inchangée : `research_runs_v2/stablecoins_365d.json` → `blocked: insufficient events`.
4. `_strict_verdict_phase3()` : `nb_events == 0` → `blocked: insufficient events` (régression leaderboard corrigée).
5. Pytest **576/576** verts.
6. Aucune claim positive tradable / live-ready / profitable dans les rapports (audit §5).
7. `config.yaml` et profils live **non modifiés**.

---

## 2. Diffs revus — keep / exclude

### Modifié (suivi git)

| Fichier | Phase 4–10 ? | Décision |
|---------|--------------|----------|
| `.gitignore` | Oui | **KEEP** — `data/collector_cache/*` ignoré sauf `README.md` + `examples/` |

### Hors périmètre (ne pas inclure dans ce commit)

| Fichier / zone | Raison | Décision |
|----------------|--------|----------|
| `config.yaml` | Interdit par mission | **NE PAS MODIFIER** |
| Profils live (`micro_live_100eur`, etc.) | Interdit | **NE PAS TOUCHER** |
| `AGENTS.md`, `docs/DEMO_VIDEO_SCRIPT.md` | Mémo / soumission hackathon | **EXCLURE** (sauf demande explicite) |
| `data/agent.sqlite*`, `data/*.jsonl`, `data/external_cache/` | Runtime agent | **NE PAS COMMITTER** |
| `**/__pycache__/`, `.pytest_cache/`, `.cursor/` | Artefacts | **NE PAS COMMITTER** |
| `.env`, credentials | Secrets | **NE PAS COMMITTER** |

### Nouveaux fichiers — **KEEP** (phases 4–10)

| Zone | Contenu |
|------|---------|
| `src/data/collectors/` | Collecteurs read-only (DefiLlama, Etherscan, Binance public, status, Wikimedia) |
| `src/signals/` | Builders d’événements |
| `src/research/` | `event_study`, `placebo`, `cost_model`, `tradeability`, `regime_analysis`, `concentration`, `paper_simulator` |
| `scripts/_event_study_common.py`, `event_study_*.py`, `demo_event_study.py` | Harness CLI |
| `tests/test_collectors_*.py`, `test_event_study.py`, `test_signals_*.py`, `test_research_*.py`, `test_tradeability.py`, `test_leaderboard_tradeability.py`, `test_paper_simulator.py`, `test_regime_analysis.py`, `test_concentration.py`, `test_placebo.py`, `test_runtime_smoke_event_study.py` | Couverture |
| `docs/ALTERNATIVE_ALPHA_PIPELINE.md`, `DATA_SOURCES.md`, `SIGNAL_REJECTION_POLICY.md`, `HYPOTHESIS_BACKLOG_PHASE_9.md`, `NEXT_5_HYPOTHESES.md`, `PAPER_OBSERVATION_DESIGN.md`, `WEIRD_BUT_TESTABLE_SIGNALS.md` | Documentation |
| `reports/` | Leaderboards, QA, RUN_LOG, research_runs(_v2), runtime_smoke, ce document |
| `data/collector_cache/README.md` | Doc cache (seul fichier racine cache autorisé) |
| `data/collector_cache/examples/` | Schémas **synthétiques** uniquement |

### **EXCLUDE** — caches réseau locaux (gitignored)

Fichiers présents en working tree mais **ne doivent pas** être `git add` :

| Fichier | Taille (octets, local) |
|---------|------------------------|
| `data/collector_cache/defillama.json` | ~662 KB |
| `data/collector_cache/wikimedia.json` | ~79 KB |
| `data/collector_cache/status_pages.json` | ~39 KB |
| `data/collector_cache/ohlc_daily_BTC.json` | ~168 KB |
| `data/collector_cache/etherscan_gas.json` | (si présent) |
| `data/collector_cache/etherscan_gas_history.json` | (si présent) |

**Autorisé à committer :** `data/collector_cache/README.md`, `data/collector_cache/examples/**` (ex. `etherscan_gas_history.example.json`).

---

## 3. Correctif artefact stablecoins Phase 3

### Problème

`reports/research_runs/stablecoins_365d.json` affichait `"verdict": "weak evidence"` avec `events_count: 0` — trompeur après règle `compute_verdict` (0 events → blocked).

### Correctifs appliqués (Agent 25)

| Fichier | Changement |
|---------|------------|
| `reports/research_runs/stablecoins_365d.json` | `verdict` → `blocked: insufficient events` ; champs `artifact_status` + `superseded_by` |
| `reports/research_runs/RUN_LOG.md` | Table + note stdout historique |
| `reports/_build_leaderboard.py` | `_strict_verdict_phase3()` : `nb_events == 0` → `blocked: insufficient events` ; comptage `blocked*` ; légende Phase 3 |
| `reports/ALPHA_RESEARCH_LEADERBOARD.{md,json}` | Régénérés (`script_verdict` = `blocked: insufficient events`) |

### Référence canonique (Phase 6 / V2)

| Artefact | Verdict | Events |
|----------|---------|--------|
| `reports/research_runs_v2/stablecoins_365d.json` | `blocked: insufficient events` | 0 |
| Leaderboard V2 | `blocked` + overlay économique | 0 |

**Ne pas** re-promouvoir stablecoins z≥1.5 sans re-run documenté dans `RUN_LOG_V2.md`.

---

## 4. Leaderboards

| Fichier | Rôle | Commit ? |
|---------|------|----------|
| `reports/_build_leaderboard.py` | Builder Phase 3 + `--v2` Phase 6 | **KEEP** |
| `reports/ALPHA_RESEARCH_LEADERBOARD.md` / `.json` | Phase 3 (historique + stablecoins corrigé) | **KEEP** |
| `reports/ALPHA_RESEARCH_LEADERBOARD_V2.md` / `.json` | Phase 6 — référence décision | **KEEP** |
| `reports/FINAL_QA_PHASE_4_10.md` | QA orchestrateur (Agent 23) | **KEEP** |
| `reports/MERGE_HYGIENE_PHASE_3.md` | Hygiène Phase 3 (archive) | **KEEP** |

Rebuild :

```powershell
.\.venv\Scripts\Activate.ps1
python reports/_build_leaderboard.py
python reports/_build_leaderboard.py --v2
```

Métriques attendues : `tradable_count: 0`, `oos_candidate_count: 0`.

---

## 5. Audit termes interdits (`reports/`)

Recherche : `tradable`, `live-ready`, `profitable`, `safe` (insensible à la casse).

| Fichier | Occurrence | Contexte | Verdict |
|---------|------------|----------|---------|
| `ALPHA_RESEARCH_LEADERBOARD*.md` / `.json` | « Tradable / live-ready signals: **0** » | Politique | **OK** |
| `ALPHA_RESEARCH_LEADERBOARD*.md` | « no signal is marked tradable, profitable, or live-ready » | Politique | **OK** |
| `FINAL_QA_PHASE_3.md`, `FINAL_QA_PHASE_4_10.md` | audit « 0 tradable » | QA | **OK** |
| `ECONOMIC_REALISM.md` | « Aucun verdict n'est live-ready » | Négation | **OK** |
| `PHASE_3_VS_PHASE_6.md` | « No signal marked tradable… » | Politique | **OK** |
| `research_runs_v2/RUN_LOG_V2.md` | « Tradable / live-ready: 0 » | Politique | **OK** |
| `RESEARCH_DECISION_BOARD.md` | « Labelliser tradable / profitable / live-ready » | **Interdit** (liste de ce qu’il ne faut pas faire) | **OK** |
| `_build_leaderboard.py` | détection verdicts interdits | Code | **OK** |

**Aucun signal marqué positivement tradable, live-ready, profitable ou safe.**

---

## 6. Validation

### pytest

```text
python -m pytest --no-header -q
→ 576 passed, 0 failed (exit 0)
```

### ruff (fichiers touchés par Agent 25)

| Périmètre | Résultat |
|-----------|----------|
| `reports/_build_leaderboard.py` | 3 avertissements (E402, F541) — préexistants / style |
| `scripts/_event_study_common.py` | 11 avertissements — préexistants / style |
| **Non bloquant** pour commit merge hygiene |

### `--help` scripts event study

Tous **OK** (exit 0) :

- `scripts/demo_event_study.py`
- `scripts/event_study_stablecoins.py`
- `scripts/event_study_wikipedia.py`
- `scripts/event_study_eth_gas.py`
- `scripts/event_study_exchange_status.py`
- `scripts/event_study_calendar.py`
- `scripts/event_study_deribit_expiry.py`

---

## 7. Procédure commit recommandée (posthackathon)

**Ne pas** `git merge master` ni ouvrir de PR vers `master` avant jugement.

```powershell
git checkout posthackathon/research-lab-phase-3-10
.\.venv\Scripts\Activate.ps1

# Ajout sélectif (exemple)
git add .gitignore
git add data/collector_cache/README.md data/collector_cache/examples/
git add docs/ALTERNATIVE_ALPHA_PIPELINE.md docs/DATA_SOURCES.md docs/SIGNAL_REJECTION_POLICY.md
git add docs/HYPOTHESIS_BACKLOG_PHASE_9.md docs/NEXT_5_HYPOTHESES.md docs/PAPER_OBSERVATION_DESIGN.md docs/WEIRD_BUT_TESTABLE_SIGNALS.md
git add src/data/ src/signals/ src/research/
git add scripts/_event_study_common.py scripts/demo_event_study.py scripts/event_study_*.py
git add tests/test_collectors_*.py tests/test_event_study.py tests/test_placebo.py tests/test_signals_*.py
git add tests/test_research_cost_model.py tests/test_regime_analysis.py tests/test_concentration.py
git add tests/test_tradeability.py tests/test_leaderboard_tradeability.py tests/test_paper_simulator.py tests/test_runtime_smoke_event_study.py
git add reports/

# Vérifier qu'aucun cache réseau n'est stagé
git status
```

Message de commit suggéré :

```text
feat(research): phases 4-10 alpha pipeline read-only + merge hygiene

Alternative alpha collectors, event studies, economic overlays, and QA reports.
Excludes live trading config; stablecoins 0-event artifacts marked blocked.
```

---

## 8. Actions post-commit (hors scope)

- Seed `etherscan_gas_history.json` si l’hypothèse gas doit être testée.
- Re-run stablecoins avec `--z-threshold 1.0` seulement si documenté dans `RUN_LOG_V2.md`.
- `ruff check --fix` sur le périmètre neuf si la CI devient stricte.

---

*Généré par l’agent merge hygiene Phase 4–10 (Agent 25) — 2026-05-19.*
