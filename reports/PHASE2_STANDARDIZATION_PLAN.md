# Phase 2 — Plan de standardisation

**Branche :** `phase30/observation-ops-ux`  
**Basé sur :** `reports/PHASE1_AUDIT_REPORT.md`  
**Objectif :** Améliorer la maintenabilité et l’onboarding sans toucher à la logique métier.

---

## Périmètre autorisé / interdit

| Autorisé | Interdit |
|----------|----------|
| `docs/*.md` (nouveaux + README) | `config.yaml` |
| `AGENTS.md`, `.cursor/rules/` | `src/execution.py`, `src/risk.py`, `src/futures_kraken_cli.py` |
| `.env.example`, `.gitignore` (exception rules) | `web/` |
| `.github/workflows/ci.yml` | Logique trading / backtest |
| `Makefile`, `scripts/README.md` | Suppression code sans preuve SAFE_TO_DELETE |
| `pyproject.toml` (scripts dev only si safe) | Upgrade deps majeures |

---

## Livrables Phase 3

### 1. Documentation (`docs/`)

| Fichier | Contenu |
|---------|---------|
| `docs/ARCHITECTURE.md` | Carte réelle agent / recherche / ops / UI ; dual portfolio ; entrypoints |
| `docs/QUALITY.md` | pytest (894), ruff, CI, politique secrets, fichiers protégés |
| `docs/DECISIONS.md` | ADR light : futures 1×, PEDSL-CY block, observation Phase 30, anti-curve-fit |

### 2. README.md

- Remplacer « 232 passed » par « 894 collected » (vérifié 2026-05-21)
- Lien vers ARCHITECTURE, QUALITY, DECISIONS

### 3. AGENTS.md

- Section « Repository audit (2026-05-21) » : score, CI, docs refs
- Pas de duplication des overrides conscients existants

### 4. `.cursor/rules/project.mdc`

- Règles projet : venv PowerShell, pytest green, fichiers off-limits, branche master frozen
- Référence docs/QUALITY et AGENTS.md

### 5. `.gitignore`

```gitignore
.cursor/*
!.cursor/rules/
!.cursor/rules/**
```

### 6. `.env.example`

Ajouts documentés (valeurs vides / safe defaults) :

- `KRAKEN_CLI_TRANSPORT=auto`
- `KRAKEN_ALPHA_PROFILE=aggressive_competition`
- `SHORTING_ENABLED=false`
- `LOOP_INTERVAL_SECONDS=` (optionnel)
- `KRAKEN_ALPHA_ROOT=` (ops VPS)

### 7. `scripts/README.md`

Catégories :

- Agent loop & safety
- Observation Phase 28–30
- Walk-forward & tournaments (phase22–27)
- Event studies & signals
- Submission & audit export
- Operator tools (`_inspect_*`, `_phase*_common`)

### 8. CI (`.github/workflows/ci.yml`)

```yaml
- Python 3.11
- pip install -r requirements.txt
- python -m pytest -q
- KRAKEN_CLI_TRANSPORT=mock (env)
```

Pas de déploiement, pas de secrets, pas de Kraken calls.

### 9. `Makefile`

Cibles : `test`, `lint`, `collect`, `dry-run-once` — wrappers documentés.

---

## Phase 4 — Dead code

**Plan :** Aucune suppression.

| Raison |
|--------|
| 0 fichier classé SAFE_TO_DELETE avec preuve d’absence d’import |
| `btc_mempool` = backlog data documenté |
| `_inspect_*` = outils opérateur |
| `_build_leaderboard.py` = importé par tests |

---

## Phase 5 — Refactor ciblé

**Décision : SKIP**

| Refactor envisagé | Pourquoi skip |
|-------------------|---------------|
| Fusion `portfolio` modules | Touche strategies + bot ; ROI doc > code |
| Logger futures keys | Touche `src/logger.py` adjacent core |
| Extraction `_phase*_common` | Large diff scripts recherche ; hors scope ops |

---

## Commits prévus (si tests verts)

1. `docs: add repository audit and architecture docs`
2. `chore: add agent rules and standard project instructions`
3. `chore: standardize scripts and env example`
4. *(skip dead code — rien à committer)*
5. `docs: final repository cleanup report`

---

## Score cible post-implémentation

| Zone | Avant | Après (estimé) |
|------|-------|----------------|
| Documentation | 6/10 | 8/10 |
| CI/CD | 3/10 | 7/10 |
| Scripts ops | 7/10 | 8/10 |
| **Global** | **72/100** | **~78/100** |
