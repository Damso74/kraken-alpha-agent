# Merge hygiene — Phase 3

**Date (UTC) :** 2026-05-19  
**Agent :** merge hygiene (post Phase 3)  
**Workspace :** `kraken-alpha-agent`

---

## 1. Diffs revus — décisions keep / revert

### Fichiers modifiés sur branche existante (`git diff HEAD`)

| Fichier | Pourquoi modifié | Phase 3 ? | Décision |
|---------|------------------|-----------|----------|
| `.gitignore` | Ignore `data/collector_cache/*` sauf `README.md` (cache collecteurs read-only) | **Oui** | **KEEP** |
| `AGENTS.md` | Mises à jour mémo agent (330 tests, rotation clés jury, dry_run footgun, anti-curve-fit Phase 2) | **Non** (mémo générale hackathon, pas livrable Phase 3) | **REVERT** ✓ |
| `docs/DEMO_VIDEO_SCRIPT.md` | Réécriture script vidéo (4 scènes, variante 60 s, cheat-sheet) | **Non** (soumission hackathon, pas pipeline alpha) | **REVERT** ✓ |

### Nouveaux fichiers (untracked) — vue d'ensemble

| Zone | Contenu | Phase 3 ? | Décision |
|------|---------|-----------|----------|
| `src/data/collectors/` | Collecteurs read-only (DefiLlama, Etherscan, status pages, Wikimedia) | Oui | **KEEP** |
| `src/signals/` | 7 signaux alternatifs + `_stats.py` | Oui | **KEEP** |
| `src/research/` | `event_study.py`, `placebo.py` | Oui | **KEEP** |
| `scripts/_event_study_common.py` + `event_study_*.py` + `demo_event_study.py` | Harness event study CLI | Oui | **KEEP** |
| `tests/test_collectors_*.py`, `test_event_study.py`, `test_placebo.py`, `test_signals_*.py`, `test_runtime_smoke_event_study.py` | Couverture Phase 3 | Oui | **KEEP** |
| `docs/ALTERNATIVE_ALPHA_PIPELINE.md`, `DATA_SOURCES.md`, `SIGNAL_REJECTION_POLICY.md` | Doc pipeline alpha | Oui | **KEEP** |
| `reports/` (leaderboard, RUN_LOG, research_runs, runtime_smoke, FINAL_QA) | Artefacts recherche + QA | Oui | **KEEP** |
| `data/collector_cache/README.md` | Doc cache (commitée via exception gitignore) | Oui | **KEEP** |
| `data/collector_cache/*.json` | Caches réseau locaux | Non (runtime) | **NE PAS COMMITTER** |
| `data/agent.sqlite*`, `data/*.jsonl`, `data/external_cache/` | Runtime agent / logs | Non | **NE PAS COMMITTER** |
| `**/__pycache__/`, `.pytest_cache/` | Artefacts Python | Non | **NE PAS COMMITTER** |

---

## 2. Correction verdict stablecoins (0 événements)

### Problème

`stablecoin_supply_z_high` avait **0 événements** mais verdict leaderboard **`weak evidence`**, ce qui sous-entend une hypothèse partiellement testée alors qu'aucune cellule n'a été exercée.

### Correctifs appliqués

| Fichier | Changement |
|---------|------------|
| `reports/_build_leaderboard.py` | `_strict_verdict()` : si `nb_events == 0` → **`blocked: insufficient events`** (plus `weak evidence`). Légende et `_next_action_default` mis à jour. |
| `scripts/_event_study_common.py` | `compute_verdict()` : si `n_events == 0` → **`blocked: insufficient events`** (1–4 events restent `weak evidence`). |
| `reports/ALPHA_RESEARCH_LEADERBOARD.md` | Régénéré via `python reports/_build_leaderboard.py` |
| `reports/ALPHA_RESEARCH_LEADERBOARD.json` | Idem — verdict stablecoins = **`blocked: insufficient events`** |

### Note résiduelle (informationnelle, non bloquante merge)

- `reports/research_runs/stablecoins_365d.json` conserve `"verdict": "weak evidence"` (artefact run Agent 7, non re-exécuté).
- Le leaderboard expose ce champ comme **`script_verdict` (informational)** ; le verdict canonique leaderboard est corrigé.
- `reports/research_runs/RUN_LOG.md` et `reports/FINAL_QA_PHASE_3.md` mentionnent encore « weak evidence » pour stablecoins dans le récit du run — cohérent avec la sortie script d'origine ; pas de re-run demandé.

---

## 3. Audit termes interdits dans `reports/`

Recherche : `tradable`, `live-ready`, `profitable` (insensible à la casse).

| Fichier | Occurrence | Contexte | Verdict |
|---------|------------|----------|---------|
| `ALPHA_RESEARCH_LEADERBOARD.md` | « Tradable / live-ready signals: **0** » | Politique Phase 3 | OK |
| `ALPHA_RESEARCH_LEADERBOARD.md` | « no signal is marked tradable, profitable, or live-ready » | Politique | OK |
| `ALPHA_RESEARCH_LEADERBOARD.json` | `"tradable_count": 0` | Métrique attendue | OK |
| `FINAL_QA_PHASE_3.md` | audit politique + « 0 signal tradable » | QA | OK |
| `_build_leaderboard.py` | détection verdicts interdits | Code builder | OK |

**Aucun signal marqué positivement tradable, live-ready ou profitable.**

---

## 4. Validation

### pytest

```text
python -m pytest --no-header -q
→ 473 tests collectés, 100 % pass (exit 0)
```

### ruff

| Périmètre | Résultat |
|-----------|----------|
| Fichiers modifiés (`reports/_build_leaderboard.py`, `scripts/_event_study_common.py`) | 10 avertissements (UP035, F401, E402, UP017) — **préexistants / style**, non introduits par le fix verdict |
| Repo entier (`ruff check .`) | **463** avertissements — dette style préexistante, **non bloquante** pour merge Phase 3 |

### `--help` scripts

Non exécuté : seul `_event_study_common.py` (module utilitaire) a été touché ; aucun CLI script modifié.

---

## 5. Décision merge

### **→ MERGE MAINTENANT**

Motifs :

1. Reverts hors-scope (`AGENTS.md`, `DEMO_VIDEO_SCRIPT.md`) appliqués.
2. Incohérence verdict stablecoins corrigée au niveau leaderboard + logique future (`compute_verdict`).
3. Suite pytest verte (473/473).
4. Aucune claim tradable/live-ready/profitable positive dans les rapports.
5. Aucune feature, refactor, ni changement `config.yaml` / profils live.

### Fichiers sûrs à committer (Phase 3)

- `.gitignore`
- `data/collector_cache/README.md` (seul fichier cache autorisé)
- `docs/ALTERNATIVE_ALPHA_PIPELINE.md`, `docs/DATA_SOURCES.md`, `docs/SIGNAL_REJECTION_POLICY.md`
- `src/data/`, `src/signals/`, `src/research/`
- `scripts/_event_study_common.py`, `scripts/demo_event_study.py`, `scripts/event_study_*.py`
- `tests/test_collectors_*.py`, `tests/test_event_study.py`, `tests/test_placebo.py`, `tests/test_signals_*.py`, `tests/test_runtime_smoke_event_study.py`
- `reports/` (leaderboard, RUN_LOG, research_runs JSON, runtime_smoke, FINAL_QA, ce document)

### Ne pas committer

- `data/collector_cache/defillama.json`, `status_pages.json`, etc.
- `data/agent.sqlite`, `data/agent.sqlite-wal`
- `data/decisions.jsonl`, `data/trades.jsonl`, `data/pnl.jsonl`
- `data/external_cache/`
- `.env`, credentials, `__pycache__/`, `.pytest_cache/`
- `.cursor/`

---

## 6. Actions post-merge (optionnelles, hors scope merge hygiene)

- Re-run `event_study_stablecoins.py` avec seuil z plus bas si l'hypothèse reste d'intérêt (mettra à jour `stablecoins_365d.json` + `script_verdict`).
- Aligner `docs/SIGNAL_REJECTION_POLICY.md` G0 si on veut documenter `blocked: insufficient events` vs `weak evidence` pour n=0 vs n∈[1,4].

---

*Généré par l'agent merge hygiene Phase 3 — 2026-05-19.*
