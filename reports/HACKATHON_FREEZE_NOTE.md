# Hackathon freeze guard — 2026-05-19

Document généré par l’agent **Hackathon freeze guard** (Agent 24).  
Objectif : figer la soumission lablab / Kraken Trading Performance et isoler le travail post-hackathon (phases recherche 3–10) sans toucher à `master`.

---

## État Git au moment du gel

| Élément | Valeur |
|--------|--------|
| **Branche courante (après action)** | `posthackathon/research-lab-phase-3-10` |
| **Branche d’origine** | `master` |
| **Remote** | `origin` → `https://github.com/Damso74/kraken-alpha-agent.git` |
| **Tracking** | `master` était aligné sur `origin/master` (pas d’avance / pas de retard) |
| **HEAD soumission (tip `master`)** | `58ac5fe` — `feat(web): functional sidebar nav + honest status badge + hero hackathon-window metric` |
| **Commit soumission documenté (réf.)** | `cbdf3d8` — `docs(submission): hackathon-window backtest + jury quickstart + post-shadow cleanup` |

---

## Classification des branches

| Branche | Rôle | Action |
|---------|------|--------|
| `master` | Branche **soumission / hackathon** (déployée Vercel, jury read-only) | **FIGÉE** — ne pas merger, ne pas force-push, ne pas déployer depuis des commits post-hackathon |
| `posthackathon/research-lab-phase-3-10` | Travail **post-hackathon** (collectors, event studies, signaux alternatifs, rapports recherche) | **CRÉÉE** le 2026-05-19 ; toute évolution phases 3–10 se fait ici |

Il n’existait **aucune** branche `submission` ni `posthackathon/*` avant cette opération.

---

## Travail local non commité (post-hackathon)

Au moment du gel, `master` portait un grand volume de fichiers **non suivis** (recherche alpha alternative, scripts `event_study_*`, `src/data/`, `src/research/`, `src/signals/`, tests associés, `reports/`, docs `DATA_SOURCES`, etc.) et une modification suivie sur `.gitignore`.

Ces changements **n’ont pas été commités sur `master`**. Après `git checkout -b posthackathon/research-lab-phase-3-10`, ils restent dans l’arbre de travail sur la branche post-hackathon uniquement.

**Recommandation :** premier commit(s) sur `posthackathon/research-lab-phase-3-10` uniquement — jamais sur `master` tant que le jury n’a pas clos la notation.

---

## Push / deploy — statut et interdictions

| Action | Statut | Consigne |
|--------|--------|----------|
| Merge vers `master` | **INTERDIT** (gel) | Reporter jusqu’à fin de jugement hackathon |
| Force-push `master` | **INTERDIT** | — |
| Deploy (Vercel / VPS live) | **NON EXÉCUTÉ** | Ne pas déployer depuis la branche post-hackathon ; `master` = surface soumission |
| Push branche post-hackathon | **Optionnel / différé** | Possible en `origin/posthackathon/research-lab-phase-3-10` pour backup — **sans** merger dans `master` |

---

## Tag local suggéré (soumission)

Aucun tag `hackathon*` n’existait au moment du gel.

**Suggestion (à créer manuellement si souhaité, une seule fois) :**

```powershell
git tag hackathon-submission-freeze-2026-05-19 58ac5fe
```

- **Cible recommandée :** `58ac5fe` (tip actuel de `master` / `origin/master`, message web + métrique fenêtre hackathon).
- **Alternative documentaire :** `cbdf3d8` si vous préférez figer le commit « docs(submission) » plutôt que le dernier commit UI.
- **Ne jamais déplacer** un tag déjà poussé ou référencé (`git tag -f` interdit sur ce nom).

---

## Synthèse des recommandations

1. **`master` reste gelé** — reflète la soumission hackathon ; pas de merge post-hackathon avant fin de jugement.
2. **Développement recherche** → branche `posthackathon/research-lab-phase-3-10` (créée, checkout actif).
3. **Tag optionnel** → `hackathon-submission-freeze-2026-05-19` sur `58ac5fe` (local, non créé automatiquement).
4. **Pas de deploy** depuis cette session ; Vercel continue de suivre `master` tel qu’il est sur GitHub.

---

## Commandes de référence (exécutées / utiles)

```powershell
git branch --show-current          # master → puis posthackathon/research-lab-phase-3-10
git status -sb
git remote -v
git checkout -b posthackathon/research-lab-phase-3-10   # exécuté
# git tag hackathon-submission-freeze-2026-05-19 58ac5fe   # suggéré, non exécuté
```

---

*Généré le 2026-05-19 — Agent 24, scope : branche + ce rapport uniquement.*
