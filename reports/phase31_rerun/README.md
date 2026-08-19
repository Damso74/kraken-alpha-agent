# Phase 31 — Rejeu de l'event study dérivés sur données reconstruites

**Date :** 2026-08-19
**Objet :** trancher par la mesure la dernière question ouverte du dépôt.

## Ce qui a changé entre les artefacts publiés et ce rejeu

1. **Les caches ont été reconstruits.** `scripts/reseed_collector_cache.py`
   les a re-téléchargés depuis les endpoints publics Binance après correction de
   la pagination du funding. `funding_rows` passe de **1 000** (exactement
   `FUNDING_PAGE_LIMIT` — la signature de la troncature) à **2 190**, la valeur
   attendue pour une fenêtre de ~1 100 jours à un point toutes les 8 heures.
2. **Le pipeline applique des tests d'inférence.** Bootstrap placebo + correction
   Benjamini-Hochberg + plancher de puissance n ≥ 30 + direction attendue
   pré-enregistrée, là où l'unique filtre était un seuil brut de 0,15 pp pris en
   valeur absolue.

## Résultat

| bundle | publié | rejeu |
|---|---|---|
| BTC 4h | `non_trivial=4`, `proceed=true`, **`overlay_only`** | `non_trivial=0`, `proceed=false`, **`weak`** |
| ETH 4h | `non_trivial=3`, `proceed=true`, **`overlay_only`** | `non_trivial=0`, `proceed=false`, **`weak`** |
| BTC 1d | `non_trivial=2`, `proceed=true`, `blocked_data` | `non_trivial=0`, `proceed=false`, `blocked_data` |
| ETH 1d | `non_trivial=2`, `proceed=true`, `blocked_data` | `non_trivial=0`, `proceed=false`, `blocked_data` |

`funding_zscore`, la dernière piste chiffrée non testée :

| | n publié | n réel | excès 72 h publié | excès 72 h réel | p | q (BH) |
|---|---|---|---|---|---|---|
| ETH 4h | 142 | 266 | +0,786 pp | **−0,177 pp** | 0,647 | 0,826 |
| BTC 4h | 126 | 243 | +0,931 pp | **+0,222 pp** | 0,428 | 0,965 |

L'excès positif monotone qui en faisait le meilleur candidat du dépôt était un
artefact de la troncature. Verdict : **`not supported`**.

## Fichiers

| Fichier | Contenu |
|---|---|
| `derivatives_event_study_summary.json` | Les 4 bundles, avec `rejection_breakdown` par couche de gate |
| `derivatives_event_study_results.csv` | 42 cellules (signal × horizon), avec p-value, q-value et couche de rejet |
| `cache_manifest.json` | sha256 + volume des 17 caches reconstruits |

## Reproduire

```bash
python scripts/reseed_collector_cache.py --dry-run   # voir ce qui serait fetché
python scripts/reseed_collector_cache.py             # ~5 min, endpoints publics
python scripts/run_derivatives_event_study_phase26.py --assets BTC ETH --timeframes 4h 1d --output-dir <dir>
```

Les caches ne sont pas versionnés (multi-Mo, `.gitignore`). `cache_manifest.json`
permet de vérifier qu'une reconstruction donne bien les mêmes volumes ; les
sha256 ne sont **pas** reproductibles octet à octet, chaque cache embarquant son
horodatage de génération.
