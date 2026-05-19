# Phase 12 baseline (WS0)

**Date :** 2026-05-19  
**Branche :** `posthackathon/research-lab-phase-3-10` (pas de merge `master`)

## Git

| Check | Résultat |
|-------|----------|
| Branche active | `posthackathon/research-lab-phase-3-10` |
| `config.yaml` diff | **vide** (hors périmètre) |
| Fichiers trading / web | non modifiés |

## Pytest (collect-only)

```
622 tests collected
```

Cible Phase 12 : **≥ 622 tests** verts après ajouts méthodologie.

## Périmètre Phase 12

- Methodology sprint : red team JSON, registre signaux, provenance cache, hold-out G4, corrections placebos/calendrier/exchange.
- **Interdit :** nouveaux signaux/collecteurs, live, merge master, données inventées dans `research_runs_phase12/`.

## Artefacts de référence Phase 11

- `reports/RED_TEAM_PHASE11.md`
- `reports/research_runs_phase11/` (sprints Agents 27–31)

## Commandes de revalidation

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest --collect-only -q
python -m pytest -q
python reports/_build_leaderboard.py --phase12
```
