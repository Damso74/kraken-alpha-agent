# Phase 6 vs Phase 11 — comparaison recherche

**Généré :** 2026-05-19 (Agent 33, archiviste leaderboard Phase 11)

Comparaison entre `reports/research_runs_v2/` (Phase 6) et le sprint Phase 11 (`reports/research_runs_phase11`). Aucune revendication de profitabilité ou de trading live.

## Delta infrastructure

| Dimension | Phase 6 | Phase 11 |
|-----------|---------|----------|
| OHLC | Binance public paginé + cache | Cache BTC 365–730j (`use-cache-only`) |
| Wikipedia | Page BTC seule, z par défaut | Panier 8 pages crypto + placebos non-crypto |
| Stablecoins | z≥1.5, 0 evt (bloqué) | Pré-enregistrement P9-SC-001-PR z≥1.0, 4 seuils figés |
| Exchange status | Incident « major », n≈2 | 9 variantes (impact, durée, venue) |
| Calendrier | `weekend_start` 730j | 5 micro-baselines journaliers 730j |
| Volume | — | P9-MS-023 (4 variantes, placebos shift/shuffle) |
| Verdicts | `not supported, move on`, `candidate for OOS retest` | Ensemble fermé Phase 11 (pas de « live-ready ») |

## Signaux comparables

### Wikipedia / attention

| | Phase 6 (`wikipedia_btc_attention`) | Phase 11 (panier) |
|---|--------------------------------|-------------------|
| Phase 6 | 16 evt, BH 0, verdict `weak evidence` | |
| `wikipedia_crypto_basket_z1.5` | | 29 evt, BH 3/8, **weak evidence** |
| `wikipedia_crypto_basket_z2.0` | | 18 evt, BH 5/8, **weak evidence** |

Phase 6 : une page, BH 0/5, weak evidence. Phase 11 : panier crypto, BH sur vol/volume aux seuils z=1,5 et 2,0 ; **révoqués par red team** → weak evidence, **0 OOS retenu**.

### Stablecoin supply

| | Phase 6 | Phase 11 (pré-enregistré z=1.0) |
|---|---------|-------------------------------|
| z par défaut | 1.5 → 0 evt | 1.0, 4 runs JSON |
| `P9-SC-001-PR-30d-high` | — | 0 evt, BH 0, **blocked** |
| `P9-SC-001-PR-30d-low` | — | 52 evt, BH 3, **weak evidence** |
| `P9-SC-001-PR-7d-high` | — | 12 evt, BH 1, **weak evidence** |
| `P9-SC-001-PR-7d-low` | — | 36 evt, BH 2, **weak evidence** |

Phase 11 exerce enfin l’hypothèse sur baisse 7j/30j (36–52 evt) mais les placebos shift/lag échouent → weak evidence, pas OOS.

### Exchange incidents

- **Phase 6 :** 2 evt, BH 0, verdict `weak evidence`
- **Phase 11 :** 9 variantes ; verdict global sprint **kill** (BH primaire vol : 0 rejets robustes).

### Calendrier

- **Phase 6 :** 105 evt, BH 0, verdict `not supported, move on`
- **Phase 11 :** cinq effets micro (US open, dimanche US, lundi Asie, 3ᵉ vendredi, fin de mois) — tous **weak evidence** après overlay coûts/turnover ; pas de candidat OOS.

### Volume shock (nouveau Phase 11)

Absent en Phase 6. P9-MS-023 : BH sur post_7 mais placebos shift/shuffle à p=1 → **weak evidence** ou **blocked** (variantes 0 evt).

## Synthèse

- **Candidats OOS Phase 11 retenus :** **0** (Wikipedia z≥1,5 / z≥2,0 révoqués par red team).
- **Stablecoins :** débloqués en volume d’événements vs Phase 6, mais falsifiés par placebos → pas d’OOS.
- **Exchange / calendrier / volume :** ne pas promouvoir ; documenter comme contrôles, weak evidence ou kill.

Rebuild : `python reports/_build_leaderboard.py --phase11`
