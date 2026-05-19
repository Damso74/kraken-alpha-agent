# Alpha research leaderboard (Phase 12)

**Généré par :** `reports/_build_leaderboard.py --phase12`
**Périmètre :** JSON sous `reports/research_runs_phase11/` (Agents 27–31, calendrier, volume, stables, exchange).

## Synthèse exécutive

- **Hypothèses / variantes évaluées :** 6
- **Candidats OOS retenus (jamais live) :** **0**
- **Signaux tradables / live-ready :** **0** (attendu)
- **Red team :** intégré depuis `reports/RED_TEAM_PHASE11.md` (fail/revoked → pas de candidat OOS).

Verdicts autorisés uniquement : `blocked`, `candidate for further OOS testing`, `kill`, `not supported`, `retry with fixed data`, `weak evidence`.

## Leaderboard

| Signal | Hypothesis ID | Dataset | Events | BH rejected | Placebo | Cost verdict | Regime verdict | Concentration | Red team | Final verdict | Next action |
|--------|---------------|---------|--------|-------------|---------|--------------|----------------|---------------|----------|---------------|-------------|
| `volume_shock_vol_z20_high` | `P9-MS-023` | BTC OHLC journalier (cache) — choc volume z p… | 18 | 3/8 | bootstrap 200 ; shift +30j post_7 p=1 ; shuffle la… | échec (seuil brut suspect) | non évalué | not_assessed | fail | **weak evidence** | Traiter comme artefact de calendrier/timing ; ne… |
| `volume_shock_vol_z60_high` | `P9-MS-023` | BTC OHLC journalier (cache) — choc volume z p… | 16 | 5/8 | bootstrap 200 ; shift +30j post_7 p=1 ; shuffle la… | échec (seuil brut suspect) | non évalué | not_assessed | fail | **weak evidence** | Traiter comme artefact de calendrier/timing ; ne… |
| `volume_shock_vol_z20_range_compression` | `P9-MS-023` | BTC OHLC journalier (cache) — choc volume z p… | 0 | 0 | bootstrap 200 ; shift +30j post_7 p=— ; shuffle la… | non évalué | non évalué | not_assessed | fail | **blocked** | Revoir seuils pré-enregistrés ou fenêtre ; pas d… |
| `volume_shock_vol_z20_low_abs_return` | `P9-MS-023` | BTC OHLC journalier (cache) — choc volume z p… | 0 | 0 | bootstrap 200 ; shift +30j post_7 p=— ; shuffle la… | non évalué | non évalué | not_assessed | fail | **blocked** | Débloquer source/cache (voir RUN_LOG_PHASE11) pu… |
| `wikipedia_crypto_basket_z1.5` | `P9-AT-012` | Wikimedia pageviews (panier 8 pages crypto) +… | 29 | 3/8 | bootstrap 200 ; shift +30j vol sig=False ; placebo… | H1 vol/volume (retour second | non évalué | not_assessed | revoked | **weak evidence** | Archiver toute promotion OOS ; aligner sur RED_T… |
| `wikipedia_crypto_basket_z2.0` | `P9-AT-012` | Wikimedia pageviews (panier 8 pages crypto) +… | 18 | 5/8 | bootstrap 200 ; shift +30j vol sig=False ; placebo… | H1 vol/volume (retour second | non évalué | not_assessed | revoked | **weak evidence** | Archiver toute promotion OOS ; aligner sur RED_T… |

## Détail par signal

### `volume_shock_vol_z20_high` · `P9-MS-023`

- **Artifact :** `reports/research_runs_phase12/volume_shock_all_365d.json#vol_z20_high`
- **Events :** 18 · **BH :** 3/8
- **Placebos :** bootstrap 200 ; shift +30j post_7 p=1 ; shuffle labels post_7 p=1
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -4.3467% below suspect threshold 0.5000% per trade; placebos shift/shuffle non passés
- **Prochaine action :** Traiter comme artefact de calendrier/timing ; ne pas promouvoir sans batterie placebo complète.

### `volume_shock_vol_z60_high` · `P9-MS-023`

- **Artifact :** `reports/research_runs_phase12/volume_shock_all_365d.json#vol_z60_high`
- **Events :** 16 · **BH :** 5/8
- **Placebos :** bootstrap 200 ; shift +30j post_7 p=1 ; shuffle labels post_7 p=1
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -4.3486% below suspect threshold 0.5000% per trade; placebos shift/shuffle non passés
- **Prochaine action :** Traiter comme artefact de calendrier/timing ; ne pas promouvoir sans batterie placebo complète.

### `volume_shock_vol_z20_range_compression` · `P9-MS-023`

- **Artifact :** `reports/research_runs_phase12/volume_shock_all_365d.json#vol_z20_range_compression`
- **Events :** 0 · **BH :** 0/0
- **Placebos :** bootstrap 200 ; shift +30j post_7 p=— ; shuffle labels post_7 p=—
- **Coûts :** non évalué · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **blocked**
- **Prochaine action :** Revoir seuils pré-enregistrés ou fenêtre ; pas de promotion sans événements alignés.

### `volume_shock_vol_z20_low_abs_return` · `P9-MS-023`

- **Artifact :** `reports/research_runs_phase12/volume_shock_all_365d.json#vol_z20_low_abs_return`
- **Events :** 0 · **BH :** 0/0
- **Placebos :** bootstrap 200 ; shift +30j post_7 p=— ; shuffle labels post_7 p=—
- **Coûts :** non évalué · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **blocked**
- **Prochaine action :** Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.

### `wikipedia_crypto_basket_z1.5` · `P9-AT-012`

- **Artifact :** `reports/research_runs_phase12/wikipedia_basket_365d.json#z1.5`
- **Events :** 29 · **BH :** 3/8
- **Placebos :** bootstrap 200 ; shift +30j vol sig=False ; placebo non-crypto vol sig=False
- **Coûts :** H1 vol/volume (retour secondaire) ; overlay retour=economically impossible · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** revoked
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -0.5319% below suspect threshold 0.5000% per trade; revoked_by_red_team (RED_TEAM_PHASE11.md)
- **Prochaine action :** Archiver toute promotion OOS ; aligner sur RED_TEAM_PHASE11.md ; hold-out explicite requis avant toute re-évaluation.

### `wikipedia_crypto_basket_z2.0` · `P9-AT-012`

- **Artifact :** `reports/research_runs_phase12/wikipedia_basket_365d.json#z2.0`
- **Events :** 18 · **BH :** 5/8
- **Placebos :** bootstrap 200 ; shift +30j vol sig=False ; placebo non-crypto vol sig=False
- **Coûts :** H1 vol/volume (retour secondaire) ; overlay retour=economically impossible · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** revoked
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -0.6803% below suspect threshold 0.5000% per trade; revoked_by_red_team (RED_TEAM_PHASE11.md)
- **Prochaine action :** Archiver toute promotion OOS ; aligner sur RED_TEAM_PHASE11.md ; hold-out explicite requis avant toute re-évaluation.

## Légende des verdicts

| Verdict | Signification |
|---------|----------------|
| `kill` | Falsification / aucune piste statistique robuste |
| `blocked` | Données ou événements insuffisants pour conclure |
| `not supported` | Test exécuté, BH ne soutient pas l’hypothèse |
| `weak evidence` | Signal fragile, placebos ou coûts non passés |
| `retry with fixed data` | Relancer après correction cache/API |
| `candidate for further OOS testing` | Seule promotion autorisée — hold-out, pas live |

## Prochaines actions prioritaires (max 3)

1. **P9-MS-023** (`volume_shock_vol_z20_range_compression`) : Revoir seuils pré-enregistrés ou fenêtre ; pas de promotion sans événements alignés.
2. **P9-MS-023** (`volume_shock_vol_z20_low_abs_return`) : Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.
3. **P9-AT-012** (`wikipedia_crypto_basket_z1.5`) : Archiver toute promotion OOS ; aligner sur RED_TEAM_PHASE11.md ; hold-out explicite requis avant toute re-évaluation.

## Références

- `reports/research_runs_phase11/RUN_LOG_PHASE11.md`
- Comparaison Phase 6 : `reports/PHASE_6_VS_PHASE11.md`
- Rebuild : `python reports/_build_leaderboard.py --phase12`
