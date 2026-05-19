# Phase 12 research runs (methodology sprint)

**Branche :** `posthackathon/research-lab-phase-3-10`  
**Date :** 2026-05-19  
**Objectif :** gates plus stricts, **0 candidat OOS** = succès.

## Runs exécutés

| Artefact | Commande | Statut |
|----------|----------|--------|
| `volume_shock_all_365d.json` | `event_study_volume_shock.py --run-all-variants --days 365 --ohlc-source cache --use-cache-only` | OK (placebos alignés `post_7`) |
| `wikipedia_basket_365d.json` | Hold-out réévalué depuis artefact Phase 11 + `ohlc_daily_BTC.json` | OK (`--enable-holdout` ; cache Wikimedia panier incomplet) |

## Notes

- Pas de nouveau signal ni collecteur.
- Wikipedia : `data/collector_cache/wikimedia.json` ne couvre pas le panier crypto (1 entrée placebo) — reprise honnête de l’artefact Phase 11 avec couche G4 hold-out.
- Volume : variantes z-high → `weak evidence` (placebos shift/shuffle sur fenêtre BH).

Rebuild leaderboard : `python reports/_build_leaderboard.py --phase12`
