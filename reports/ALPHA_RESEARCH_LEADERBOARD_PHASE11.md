# Alpha research leaderboard (Phase 11)

**Généré par :** `reports/_build_leaderboard.py --phase11`
**Périmètre :** JSON sous `reports/research_runs_phase11/` (Agents 27–31, calendrier, volume, stables, exchange).

## Synthèse exécutive

- **Hypothèses / variantes évaluées :** 24
- **Candidats OOS retenus (jamais live) :** **0**
- **Signaux tradables / live-ready :** **0** (attendu)
- **Red team :** intégré depuis `reports/RED_TEAM_PHASE11.md` (fail/revoked → pas de candidat OOS).

Verdicts autorisés uniquement : `blocked`, `candidate for further OOS testing`, `kill`, `not supported`, `retry with fixed data`, `weak evidence`.

## Leaderboard

| Signal | Hypothesis ID | Dataset | Events | BH rejected | Placebo | Cost verdict | Regime verdict | Concentration | Red team | Final verdict | Next action |
|--------|---------------|---------|--------|-------------|---------|--------------|----------------|---------------|----------|---------------|-------------|
| `calendar_us_market_open_window` | `P9-CA-032` | Kraken/Binance cache BTC OHLC + calendrier dé… | 525 | 2/8 | bootstrap 200 ; same-weekday post_7 p=0.9353 ; shi… | échec (seuil brut suspect) | calendrier fixe (us_ma | not_assessed | warning | **weak evidence** | Conserver en recherche descriptive ; pas de reve… |
| `calendar_sunday_us_evening` | `P9-CAL-SUN-US` | Kraken/Binance cache BTC OHLC + calendrier dé… | 105 | 0/8 | bootstrap 200 ; same-weekday post_7 p=0.9552 ; shi… | échec (seuil brut suspect) | calendrier fixe (sunda | not_assessed | fail | **weak evidence** | Conserver en recherche descriptive ; pas de reve… |
| `calendar_monday_asia_open` | `P9-CAL-MON-ASIA` | Kraken/Binance cache BTC OHLC + calendrier dé… | 105 | 2/8 | bootstrap 200 ; same-weekday post_7 p=0.9751 ; shi… | échec (seuil brut suspect) | calendrier fixe (monda | not_assessed | fail | **weak evidence** | Conserver en recherche descriptive ; pas de reve… |
| `calendar_third_friday` | `P9-CA-037` | Kraken/Binance cache BTC OHLC + calendrier dé… | 25 | 0/8 | bootstrap 200 ; same-weekday post_7 p=0.7662 ; shi… | dominé par coûts | calendrier fixe (third | not_assessed | fail | **weak evidence** | Conserver en recherche descriptive ; pas de reve… |
| `calendar_month_end` | `P9-CAL-MONTH-END` | Kraken/Binance cache BTC OHLC + calendrier dé… | 24 | 0/8 | bootstrap 200 ; same-weekday post_7 p=0.3483 ; shi… | échec (seuil brut suspect) | calendrier fixe (month | not_assessed | fail | **weak evidence** | Conserver en recherche descriptive ; pas de reve… |
| `volume_shock_vol_z20_high` | `P9-MS-023` | BTC OHLC journalier (cache) — choc volume z p… | 18 | 3/8 | bootstrap 200 ; shift +30j post_3 p=1 ; shuffle la… | échec (seuil brut suspect) | non évalué | not_assessed | fail | **weak evidence** | Traiter comme artefact de calendrier/timing ; ne… |
| `volume_shock_vol_z60_high` | `P9-MS-023` | BTC OHLC journalier (cache) — choc volume z p… | 16 | 5/8 | bootstrap 200 ; shift +30j post_3 p=1 ; shuffle la… | échec (seuil brut suspect) | non évalué | not_assessed | fail | **weak evidence** | Traiter comme artefact de calendrier/timing ; ne… |
| `volume_shock_vol_z20_range_compression` | `P9-MS-023` | BTC OHLC journalier (cache) — choc volume z p… | 0 | 0 | bootstrap 200 ; shift +30j post_3 p=— ; shuffle la… | non évalué | non évalué | not_assessed | fail | **blocked** | Revoir seuils pré-enregistrés ou fenêtre ; pas d… |
| `volume_shock_vol_z20_low_abs_return` | `P9-MS-023` | BTC OHLC journalier (cache) — choc volume z p… | 0 | 0 | bootstrap 200 ; shift +30j post_3 p=— ; shuffle la… | non évalué | non évalué | not_assessed | fail | **blocked** | Débloquer source/cache (voir RUN_LOG_PHASE11) pu… |
| `wikipedia_crypto_basket_z1.5` | `P9-AT-012` | Wikimedia pageviews (panier 8 pages crypto) +… | 29 | 3/8 | bootstrap 200 ; shift +30j vol sig=False ; placebo… | H1 vol/volume (retour second | non évalué | not_assessed | revoked | **weak evidence** | Archiver toute promotion OOS ; aligner sur RED_T… |
| `wikipedia_crypto_basket_z2.0` | `P9-AT-012` | Wikimedia pageviews (panier 8 pages crypto) +… | 18 | 5/8 | bootstrap 200 ; shift +30j vol sig=False ; placebo… | H1 vol/volume (retour second | non évalué | not_assessed | revoked | **weak evidence** | Archiver toute promotion OOS ; aligner sur RED_T… |
| `exchange_status_unscheduled_incidents` | `P9-ES-PH11-unscheduled_incidents` | Statuspage Kraken/Coinbase + BTC OHLC cache 3… | 29 | 0/3 | timestamps aléatoires n=200 ; shift +14j | échec (seuil brut suspect) | non évalué | not_assessed | fail | **kill** | Clôturer la variante ; documenter dans le backlo… |
| `exchange_status_scheduled_maintenance` | `P9-ES-PH11-scheduled_maintenance` | Statuspage Kraken/Coinbase + BTC OHLC cache 3… | 1 | 0/1 | timestamps aléatoires n=200 ; shift +14j | échec (seuil brut suspect) | non évalué | not_assessed | fail | **blocked** | Débloquer source/cache (voir RUN_LOG_PHASE11) pu… |
| `exchange_status_impact_minor` | `P9-ES-PH11-impact_minor` | Statuspage Kraken/Coinbase + BTC OHLC cache 3… | 29 | 0/3 | timestamps aléatoires n=200 ; shift +14j | échec (seuil brut suspect) | non évalué | not_assessed | fail | **kill** | Clôturer la variante ; documenter dans le backlo… |
| `exchange_status_impact_major` | `P9-ES-PH11-impact_major` | Statuspage Kraken/Coinbase + BTC OHLC cache 3… | 1 | 0/3 | timestamps aléatoires n=200 ; shift +14j | échec (seuil brut suspect) | non évalué | not_assessed | fail | **blocked** | Débloquer source/cache (voir RUN_LOG_PHASE11) pu… |
| `exchange_status_impact_critical` | `P9-ES-PH11-impact_critical` | Statuspage Kraken/Coinbase + BTC OHLC cache 3… | 1 | 0/3 | timestamps aléatoires n=200 ; shift +14j | dominé par coûts | non évalué | not_assessed | fail | **blocked** | Débloquer source/cache (voir RUN_LOG_PHASE11) pu… |
| `exchange_status_duration_gt_30m` | `P9-ES-PH11-duration_gt_30m` | Statuspage Kraken/Coinbase + BTC OHLC cache 3… | 25 | 0/3 | timestamps aléatoires n=200 ; shift +14j | échec (seuil brut suspect) | non évalué | not_assessed | fail | **kill** | Clôturer la variante ; documenter dans le backlo… |
| `exchange_status_venue_kraken` | `P9-ES-PH11-venue_kraken` | Statuspage Kraken/Coinbase + BTC OHLC cache 3… | 23 | 0/3 | timestamps aléatoires n=200 ; shift +14j | échec (seuil brut suspect) | non évalué | not_assessed | fail | **kill** | Clôturer la variante ; documenter dans le backlo… |
| `exchange_status_venue_coinbase` | `P9-ES-PH11-venue_coinbase` | Statuspage Kraken/Coinbase + BTC OHLC cache 3… | 15 | 0/3 | timestamps aléatoires n=200 ; shift +14j | échec (seuil brut suspect) | non évalué | not_assessed | fail | **kill** | Clôturer la variante ; documenter dans le backlo… |
| `exchange_status_basket_combined` | `P9-ES-PH11-basket_combined` | Statuspage Kraken/Coinbase + BTC OHLC cache 3… | 30 | 0/3 | timestamps aléatoires n=200 ; shift +14j | échec (seuil brut suspect) | non évalué | not_assessed | fail | **kill** | Clôturer la variante ; documenter dans le backlo… |
| `stablecoin_supply_change_30d_30d_high` | `P9-SC-001-PR-30d-high` | DefiLlama stablecoin supply + BTC/ETH OHLC ca… | 0 | 0 | bootstrap 0 pass=None ; shift 30j pass=None ; lag … | non évalué | non évalué | not_assessed | fail | **blocked** | Débloquer source/cache (voir RUN_LOG_PHASE11) pu… |
| `stablecoin_supply_change_30d_30d_low` | `P9-SC-001-PR-30d-low` | DefiLlama stablecoin supply + BTC/ETH OHLC ca… | 52 | 3/3 | bootstrap 200 pass=True ; shift 30j pass=False ; l… | échec (seuil brut suspect) | non évalué | not_assessed | fail | **weak evidence** | Conserver en recherche descriptive ; pas de reve… |
| `stablecoin_supply_change_7d_7d_high` | `P9-SC-001-PR-7d-high` | DefiLlama stablecoin supply + BTC/ETH OHLC ca… | 12 | 1/3 | bootstrap 200 pass=True ; shift 30j pass=False ; l… | marginal (recherche uniqueme | non évalué | not_assessed | fail | **weak evidence** | Conserver en recherche descriptive ; pas de reve… |
| `stablecoin_supply_change_7d_7d_low` | `P9-SC-001-PR-7d-low` | DefiLlama stablecoin supply + BTC/ETH OHLC ca… | 36 | 2/3 | bootstrap 200 pass=True ; shift 30j pass=False ; l… | échec (seuil brut suspect) | non évalué | not_assessed | fail | **weak evidence** | Conserver en recherche descriptive ; pas de reve… |

## Détail par signal

### `calendar_us_market_open_window` · `P9-CA-032`

- **Artifact :** `reports/research_runs_phase11/calendar_micro_baselines.json#us_market_open_window`
- **Events :** 525 · **BH :** 2/8
- **Placebos :** bootstrap 200 ; same-weekday post_7 p=0.9353 ; shift +14..60d post_7 p=1
- **Coûts :** échec (seuil brut suspect) · **Régime :** calendrier fixe (us_market_open_window)
- **Concentration :** not_assessed
- **Red team :** warning
- **Verdict final :** **weak evidence**
- **Caveat :** turnover proxy 71.5% > 30% (signal too noisy for distinct events); gross mean 0.3356% below suspect threshold 0.5000% per trade
- **Prochaine action :** Conserver en recherche descriptive ; pas de revendication trading.

### `calendar_sunday_us_evening` · `P9-CAL-SUN-US`

- **Artifact :** `reports/research_runs_phase11/calendar_micro_baselines.json#sunday_us_evening`
- **Events :** 105 · **BH :** 0/8
- **Placebos :** bootstrap 200 ; same-weekday post_7 p=0.9552 ; shift +14..60d post_7 p=0.8259
- **Coûts :** échec (seuil brut suspect) · **Régime :** calendrier fixe (sunday_us_evening)
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean 0.2507% below suspect threshold 0.5000% per trade
- **Prochaine action :** Conserver en recherche descriptive ; pas de revendication trading.

### `calendar_monday_asia_open` · `P9-CAL-MON-ASIA`

- **Artifact :** `reports/research_runs_phase11/calendar_micro_baselines.json#monday_asia_open`
- **Events :** 105 · **BH :** 2/8
- **Placebos :** bootstrap 200 ; same-weekday post_7 p=0.9751 ; shift +14..60d post_7 p=0.8358
- **Coûts :** échec (seuil brut suspect) · **Régime :** calendrier fixe (monday_asia_open)
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean 0.2507% below suspect threshold 0.5000% per trade
- **Prochaine action :** Conserver en recherche descriptive ; pas de revendication trading.

### `calendar_third_friday` · `P9-CA-037`

- **Artifact :** `reports/research_runs_phase11/calendar_micro_baselines.json#third_friday`
- **Events :** 25 · **BH :** 0/8
- **Placebos :** bootstrap 200 ; same-weekday post_7 p=0.7662 ; shift +14..60d post_7 p=0.8657
- **Coûts :** dominé par coûts · **Régime :** calendrier fixe (third_friday)
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross 0.6188% does not exceed round-trip cost 1.0000%
- **Prochaine action :** Conserver en recherche descriptive ; pas de revendication trading.

### `calendar_month_end` · `P9-CAL-MONTH-END`

- **Artifact :** `reports/research_runs_phase11/calendar_micro_baselines.json#month_end`
- **Events :** 24 · **BH :** 0/8
- **Placebos :** bootstrap 200 ; same-weekday post_7 p=0.3483 ; shift +14..60d post_7 p=0.806
- **Coûts :** échec (seuil brut suspect) · **Régime :** calendrier fixe (month_end)
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -0.4703% below suspect threshold 0.5000% per trade
- **Prochaine action :** Conserver en recherche descriptive ; pas de revendication trading.

### `volume_shock_vol_z20_high` · `P9-MS-023`

- **Artifact :** `reports/research_runs_phase11/volume_shock_all_365d.json#vol_z20_high`
- **Events :** 18 · **BH :** 3/8
- **Placebos :** bootstrap 200 ; shift +30j post_3 p=1 ; shuffle labels post_3 p=1
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -4.3467% below suspect threshold 0.5000% per trade; placebos shift/shuffle non passés
- **Prochaine action :** Traiter comme artefact de calendrier/timing ; ne pas promouvoir sans batterie placebo complète.

### `volume_shock_vol_z60_high` · `P9-MS-023`

- **Artifact :** `reports/research_runs_phase11/volume_shock_all_365d.json#vol_z60_high`
- **Events :** 16 · **BH :** 5/8
- **Placebos :** bootstrap 200 ; shift +30j post_3 p=1 ; shuffle labels post_3 p=1
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -4.3486% below suspect threshold 0.5000% per trade; placebos shift/shuffle non passés
- **Prochaine action :** Traiter comme artefact de calendrier/timing ; ne pas promouvoir sans batterie placebo complète.

### `volume_shock_vol_z20_range_compression` · `P9-MS-023`

- **Artifact :** `reports/research_runs_phase11/volume_shock_all_365d.json#vol_z20_range_compression`
- **Events :** 0 · **BH :** 0/0
- **Placebos :** bootstrap 200 ; shift +30j post_3 p=— ; shuffle labels post_3 p=—
- **Coûts :** non évalué · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **blocked**
- **Prochaine action :** Revoir seuils pré-enregistrés ou fenêtre ; pas de promotion sans événements alignés.

### `volume_shock_vol_z20_low_abs_return` · `P9-MS-023`

- **Artifact :** `reports/research_runs_phase11/volume_shock_all_365d.json#vol_z20_low_abs_return`
- **Events :** 0 · **BH :** 0/0
- **Placebos :** bootstrap 200 ; shift +30j post_3 p=— ; shuffle labels post_3 p=—
- **Coûts :** non évalué · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **blocked**
- **Prochaine action :** Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.

### `wikipedia_crypto_basket_z1.5` · `P9-AT-012`

- **Artifact :** `reports/research_runs_phase11/wikipedia_basket_365d.json#z1.5`
- **Events :** 29 · **BH :** 3/8
- **Placebos :** bootstrap 200 ; shift +30j vol sig=False ; placebo non-crypto vol sig=False
- **Coûts :** H1 vol/volume (retour secondaire) ; overlay retour=economically impossible · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** revoked
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -0.5319% below suspect threshold 0.5000% per trade; revoked_by_red_team (RED_TEAM_PHASE11.md)
- **Prochaine action :** Archiver toute promotion OOS ; aligner sur RED_TEAM_PHASE11.md ; hold-out explicite requis avant toute re-évaluation.

### `wikipedia_crypto_basket_z2.0` · `P9-AT-012`

- **Artifact :** `reports/research_runs_phase11/wikipedia_basket_365d.json#z2.0`
- **Events :** 18 · **BH :** 5/8
- **Placebos :** bootstrap 200 ; shift +30j vol sig=False ; placebo non-crypto vol sig=False
- **Coûts :** H1 vol/volume (retour secondaire) ; overlay retour=economically impossible · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** revoked
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -0.6803% below suspect threshold 0.5000% per trade; revoked_by_red_team (RED_TEAM_PHASE11.md)
- **Prochaine action :** Archiver toute promotion OOS ; aligner sur RED_TEAM_PHASE11.md ; hold-out explicite requis avant toute re-évaluation.

### `exchange_status_unscheduled_incidents` · `P9-ES-PH11-unscheduled_incidents`

- **Artifact :** `reports/research_runs_phase11/exchange_status_deep_dive_365d.json#unscheduled_incidents`
- **Events :** 29 · **BH :** 0/3
- **Placebos :** timestamps aléatoires n=200 ; shift +14j
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **kill**
- **Caveat :** gross mean 0.3736% below suspect threshold 0.5000% per trade
- **Prochaine action :** Clôturer la variante ; documenter dans le backlog Phase 12 si besoin.

### `exchange_status_scheduled_maintenance` · `P9-ES-PH11-scheduled_maintenance`

- **Artifact :** `reports/research_runs_phase11/exchange_status_deep_dive_365d.json#scheduled_maintenance`
- **Events :** 1 · **BH :** 0/1
- **Placebos :** timestamps aléatoires n=200 ; shift +14j
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **blocked**
- **Caveat :** only 1 events (< 5); insufficient power; gross mean 0.0000% below suspect threshold 0.5000% per trade
- **Prochaine action :** Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.

### `exchange_status_impact_minor` · `P9-ES-PH11-impact_minor`

- **Artifact :** `reports/research_runs_phase11/exchange_status_deep_dive_365d.json#impact_minor`
- **Events :** 29 · **BH :** 0/3
- **Placebos :** timestamps aléatoires n=200 ; shift +14j
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **kill**
- **Caveat :** gross mean 0.3610% below suspect threshold 0.5000% per trade
- **Prochaine action :** Clôturer la variante ; documenter dans le backlog Phase 12 si besoin.

### `exchange_status_impact_major` · `P9-ES-PH11-impact_major`

- **Artifact :** `reports/research_runs_phase11/exchange_status_deep_dive_365d.json#impact_major`
- **Events :** 1 · **BH :** 0/3
- **Placebos :** timestamps aléatoires n=200 ; shift +14j
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **blocked**
- **Caveat :** only 1 events (< 5); insufficient power; gross mean -0.2527% below suspect threshold 0.5000% per trade
- **Prochaine action :** Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.

### `exchange_status_impact_critical` · `P9-ES-PH11-impact_critical`

- **Artifact :** `reports/research_runs_phase11/exchange_status_deep_dive_365d.json#impact_critical`
- **Events :** 1 · **BH :** 0/3
- **Placebos :** timestamps aléatoires n=200 ; shift +14j
- **Coûts :** dominé par coûts · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **blocked**
- **Caveat :** only 1 events (< 5); insufficient power; gross 0.7152% does not exceed round-trip cost 1.0000%
- **Prochaine action :** Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.

### `exchange_status_duration_gt_30m` · `P9-ES-PH11-duration_gt_30m`

- **Artifact :** `reports/research_runs_phase11/exchange_status_deep_dive_365d.json#duration_gt_30m`
- **Events :** 25 · **BH :** 0/3
- **Placebos :** timestamps aléatoires n=200 ; shift +14j
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **kill**
- **Caveat :** gross mean 0.3439% below suspect threshold 0.5000% per trade
- **Prochaine action :** Clôturer la variante ; documenter dans le backlog Phase 12 si besoin.

### `exchange_status_venue_kraken` · `P9-ES-PH11-venue_kraken`

- **Artifact :** `reports/research_runs_phase11/exchange_status_deep_dive_365d.json#venue_kraken`
- **Events :** 23 · **BH :** 0/3
- **Placebos :** timestamps aléatoires n=200 ; shift +14j
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **kill**
- **Caveat :** gross mean 0.3675% below suspect threshold 0.5000% per trade
- **Prochaine action :** Clôturer la variante ; documenter dans le backlog Phase 12 si besoin.

### `exchange_status_venue_coinbase` · `P9-ES-PH11-venue_coinbase`

- **Artifact :** `reports/research_runs_phase11/exchange_status_deep_dive_365d.json#venue_coinbase`
- **Events :** 15 · **BH :** 0/3
- **Placebos :** timestamps aléatoires n=200 ; shift +14j
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **kill**
- **Caveat :** gross mean 0.3309% below suspect threshold 0.5000% per trade
- **Prochaine action :** Clôturer la variante ; documenter dans le backlog Phase 12 si besoin.

### `exchange_status_basket_combined` · `P9-ES-PH11-basket_combined`

- **Artifact :** `reports/research_runs_phase11/exchange_status_deep_dive_365d.json#basket_combined`
- **Events :** 30 · **BH :** 0/3
- **Placebos :** timestamps aléatoires n=200 ; shift +14j
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **kill**
- **Caveat :** gross mean 0.3736% below suspect threshold 0.5000% per trade
- **Prochaine action :** Clôturer la variante ; documenter dans le backlog Phase 12 si besoin.

### `stablecoin_supply_change_30d_30d_high` · `P9-SC-001-PR-30d-high`

- **Artifact :** `reports/research_runs_phase11/p9-sc-001-pr-30d-high.json`
- **Events :** 0 · **BH :** 0/0
- **Placebos :** bootstrap 0 pass=None ; shift 30j pass=None ; lag inversé pass=None ; batterie globale pass=False
- **Coûts :** non évalué · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **blocked**
- **Caveat :** 0 événement aligné sur la fenêtre
- **Prochaine action :** Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.

### `stablecoin_supply_change_30d_30d_low` · `P9-SC-001-PR-30d-low`

- **Artifact :** `reports/research_runs_phase11/p9-sc-001-pr-30d-low.json`
- **Events :** 52 · **BH :** 3/3
- **Placebos :** bootstrap 200 pass=True ; shift 30j pass=False ; lag inversé pass=True ; batterie globale pass=False
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -2.8066% below suspect threshold 0.5000% per trade
- **Prochaine action :** Conserver en recherche descriptive ; pas de revendication trading.

### `stablecoin_supply_change_7d_7d_high` · `P9-SC-001-PR-7d-high`

- **Artifact :** `reports/research_runs_phase11/p9-sc-001-pr-7d-high.json`
- **Events :** 12 · **BH :** 1/3
- **Placebos :** bootstrap 200 pass=True ; shift 30j pass=False ; lag inversé pass=False ; batterie globale pass=False
- **Coûts :** marginal (recherche uniquement) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Prochaine action :** Conserver en recherche descriptive ; pas de revendication trading.

### `stablecoin_supply_change_7d_7d_low` · `P9-SC-001-PR-7d-low`

- **Artifact :** `reports/research_runs_phase11/p9-sc-001-pr-7d-low.json`
- **Events :** 36 · **BH :** 2/3
- **Placebos :** bootstrap 200 pass=True ; shift 30j pass=False ; lag inversé pass=False ; batterie globale pass=False
- **Coûts :** échec (seuil brut suspect) · **Régime :** non évalué
- **Concentration :** not_assessed
- **Red team :** fail
- **Verdict final :** **weak evidence**
- **Caveat :** gross mean -3.4550% below suspect threshold 0.5000% per trade
- **Prochaine action :** Conserver en recherche descriptive ; pas de revendication trading.

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

1. **P9-ES-PH11-impact_critical** (`exchange_status_impact_critical`) : Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.
2. **P9-ES-PH11-impact_major** (`exchange_status_impact_major`) : Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.
3. **P9-ES-PH11-scheduled_maintenance** (`exchange_status_scheduled_maintenance`) : Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness.

## Références

- `reports/research_runs_phase11/RUN_LOG_PHASE11.md`
- Comparaison Phase 6 : `reports/PHASE_6_VS_PHASE11.md`
- Rebuild : `python reports/_build_leaderboard.py --phase11`
