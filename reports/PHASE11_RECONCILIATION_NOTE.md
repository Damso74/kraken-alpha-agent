# Note de réconciliation Phase 11

**Date :** 2026-05-19  
**Branche :** `posthackathon/research-lab-phase-3-10`  
**Agent :** réconciliation post-hackathon (alignement leaderboard ↔ red team)

---

## 1. Incohérence initiale

| Source | Candidats OOS déclarés |
|--------|------------------------|
| `ALPHA_RESEARCH_LEADERBOARD_PHASE11.md` / `.json` (avant rebuild) | **2** (`wikipedia_crypto_basket_z1.5`, `z2.0`) |
| `RED_TEAM_PHASE11.md` | **0** — Wikipedia **FAIL**, interdiction explicite du libellé « candidate OOS » |
| `FINAL_QA_PHASE11.md` §9 | **0** (verdict QA final) |

**Cause racine :** `compute_phase11_verdict` / script Wikipedia trop laxiste (promotion dès BH vol/volume sans hold-out, sans overlay return, sans red team). Le builder Phase 11 recopiait ce verdict et affichait `red_team_status: en attente (Agent 32)` alors que `RED_TEAM_PHASE11.md` était déjà livré.

**Vérité consolidée :** **0 candidat OOS retenu** pour tout le sprint Phase 11.

---

## 2. Fichiers corrigés

| Fichier | Action |
|---------|--------|
| `reports/_build_leaderboard.py` | Règle explicite : `red_team_status` ∈ {fail, revoked} → `final_verdict` ≠ `candidate for further OOS testing` ; tag `revoked_by_red_team` pour Wikipedia ; statuts red team par signal |
| `reports/ALPHA_RESEARCH_LEADERBOARD_PHASE11.md` | Régénéré (`oos_candidate_count: 0`) |
| `reports/ALPHA_RESEARCH_LEADERBOARD_PHASE11.json` | Idem |
| `reports/PHASE_6_VS_PHASE11.md` | Synthèse : **0 OOS** ; Wikipedia révoqués |
| `reports/FINAL_QA_PHASE11.md` | Addendum §14 (ci-dessous) |
| `tests/test_leaderboard_tradeability.py` | +4 tests red team / Phase 11 |

**Rebuild :**

```powershell
.\.venv\Scripts\Activate.ps1
python reports/_build_leaderboard.py --phase11
```

---

## 3. Verdicts consolidés (familles)

| Famille | Verdict final | OOS |
|---------|---------------|-----|
| Calendrier (5 effets) | weak evidence (coûts / turnover / pas return BH) | Non |
| Stablecoins P9-SC-001-PR ×4 | blocked (30d-high) ou weak evidence (placebos non passés) | Non |
| Volume shock P9-MS-023 | weak evidence ou blocked (0 evt) ; placebos shift/shuffle p=1 | Non |
| Wikipedia P9-AT-012 z1.5 / z2.0 | weak evidence + **revoked_by_red_team** | Non |
| Exchange status (9 variantes) | kill ou blocked | Non |
| **Total retenu** | — | **0** |

Aucune revendication tradable, live-ready ou profitable.

---

## 4. Validation

| Contrôle | Résultat |
|----------|----------|
| `pytest tests/test_leaderboard_tradeability.py` | 14 passed |
| `pytest` (suite complète, venv) | **622 passed** |
| `python reports/_build_leaderboard.py --phase11` | `OOS candidates: 0` |
| `python reports/_build_leaderboard.py --help` | OK |
| `config.yaml` / profils live | **non modifiés** |

---

## 5. Confirmation gouvernance

- **Merge vers `master` :** non effectué (hors périmètre).
- **Deploy (Vercel / VPS) :** non effectué.
- **Branche :** `posthackathon/research-lab-phase-3-10` prête pour commit utilisateur.

---

## 6. Préparation commit (instructions)

### À inclure (`git add`)

- `reports/_build_leaderboard.py`
- `reports/ALPHA_RESEARCH_LEADERBOARD_PHASE11.md`
- `reports/ALPHA_RESEARCH_LEADERBOARD_PHASE11.json`
- `reports/PHASE_6_VS_PHASE11.md`
- `reports/PHASE11_RECONCILIATION_NOTE.md`
- `reports/FINAL_QA_PHASE11.md` (addendum)
- `tests/test_leaderboard_tradeability.py`
- Tout le lot Phase 3–11 déjà présent sur la branche : `src/research/`, `src/signals/`, `src/data/collectors/`, `scripts/event_study_*.py`, `docs/`, `reports/research_runs_phase11/*.json`, `reports/RED_TEAM_PHASE11.md`, etc.

### À exclure

- `data/collector_cache/*.json` (caches réels locaux — seulement `examples/` et README)
- `.env`, `data/jury_readonly_credentials.md`, clés API
- `export/`, `web/.next/`, `__pycache__/`

### Message suggéré (si commit)

```
feat(research): alternative alpha pipeline phases 3-11 with honest-negative verdicts
```

**Commit non exécuté par l’agent** — à lancer manuellement après relecture.

---

## Références

- `reports/RED_TEAM_PHASE11.md`
- `reports/FINAL_QA_PHASE11.md`
- `docs/SIGNAL_REJECTION_POLICY.md`
