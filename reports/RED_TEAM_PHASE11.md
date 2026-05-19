# Red team quant — Phase 11

**Agent :** 32 (red team)  
**Date (UTC) :** 2026-05-19  
**Branche :** `posthackathon/research-lab-phase-3-10` (aucun merge `master`, aucun changement `config.yaml`)  
**Périmètre :** lecture de tous les JSON sous `reports/research_runs_phase11/`, `RUN_LOG_PHASE11.md`, `RUN_LOG.md` ; comparaison aux rapports Phase 3/6 (`ALPHA_RESEARCH_LEADERBOARD_V2.md`, `RESEARCH_DECISION_BOARD.md`).

**Mandat :** tenter de **tuer** chaque résultat Phase 11. Un verdict red team **PASS** est exceptionnel ; **WARNING** = signal de recherche au mieux, jamais tradable ; **FAIL** = ne pas promouvoir, ne pas allouer d’OOS.

---

## Synthèse exécutive

| Sprint | Verdict red team | Promotion OOS autorisée ? |
|--------|------------------|---------------------------|
| Calendrier (micro-baselines) | **FAIL** | Non |
| Stablecoins (P9-SC-001-PR ×4) | **FAIL** | Non |
| Volume shock (P9-MS-023) | **FAIL** | Non |
| Wikipedia basket | **FAIL** | **Non — révoquer « candidate OOS »** |
| Exchange status (deep dive) | **FAIL** | Non (déjà `kill`) |

**Conclusion globale Phase 11 :** aucun sprint ne survit à une revue adversarial. Le seul artefact qui contrevient à la ligne conservatrice du reste du programme est `wikipedia_basket_365d.json` (`phase11_final_verdict: candidate for further OOS testing`) — **cette étiquette est rejetée** : il n’y a **aucune partition train/OOS**, les placebos sont heuristiques, et le signal économique sur `return` est absent ou négatif.

---

## Grille d’audit transversale (12 points)

| # | Contrôle | Constats Phase 11 |
|---|---------|-------------------|
| 1 | **Lookahead bias** | z-scores rolling excluent le point courant (`_stats.rolling_z_scores`) → OK pour wiki/stablecoins/volume. Supply change et alignement journalier OHLC restent sensibles au **lag de publication DefiLlama** (non documenté dans les JSON). |
| 2 | **Alignement timestamps** | Alignement « même jour UTC » (`align_events_to_daily_candles`) : incidents intraday et pageviews journaliers sont **compressés** en une bougie — risque de mélanger signal et réaction. |
| 3 | **Duplication d’événements** | **FAIL calendrier :** `sunday_us_evening` et `monday_asia_open` produisent **exactement le même ensemble de 105 timestamps** sur le cache 736 bougies (vérifié empiriquement). Deux hypothèses pré-enregistrées, un seul signal. |
| 4 | **Événements trop peu nombreux** | Exchange status : 1 incident major/critical ; scheduled n=1. Volume shock : n=16–18. Wikipedia z=2.0 : n=18. Stablecoins 7d-high : n=12. Tous sous le seuil de confiance pour inférence causale ou OOS. |
| 5 | **Misusage BH / multi-test** | BH appliqué par variante, mais **familles corrélées** (4 variantes volume, 4 seuils stablecoin, 2 seuils wiki, 5 effets calendrier) sans correction inter-famille → risque de « winner’s curse ». Volume shock : script `supported` dès BH≥1 **sans** exiger robustesse placebo sur la même fenêtre. |
| 6 | **Placebos trop faibles** | **Exchange status :** clé `random_timestamps` **recopie les cellules primaires** — ce n’est pas un placebo de dates aléées (bug sémantique / faux négatif de robustesse). **Wikipedia :** shift +30j = heuristique `realized_vol post_3 mean > 0.02`, pas de p-value bootstrap. **Volume shock :** placebos shift/shuffle sur `return/post_3` alors que les rejets BH sont sur `post_7` / `max_drawdown`. |
| 7 | **Dominé par les coûts** | Calendrier : overlay économique rejette tout (`economic_reject: true`, net négatif). Stablecoins / wiki / volume : effets `return` inférieurs au round-trip 1 % ou négatifs sur la cellule pertinente. |
| 8 | **Risque de concentration** | Wikipedia z=2.0 : **50 %** des événements en août 2025 (9/18), **28 %** en février 2026 — non testé par analyse de leave-one-month-out. Volume shock : n=18 sur 371 jours, effet post_7 fortement influencé par quelques chocs. |
| 9 | **Instabilité de régime** | Fenêtre unique ~365 j (calendrier 730 j) ; pas de split bull/bear ; stablecoins contraction/low dominant en régime récent — non généralisable sans hold-out. |
| 10 | **Fuite de cible (target leakage)** | Panier Wikipedia agrège 8 pages crypto dont « Cryptocurrency exchange » (55 hits z≥1.5) — **fortement corrélé** au volume BTC ; tester vol/volume **post** attention est partiellement tautologique. |
| 11 | **Contamination cache API** | Volume shock + calendrier : `--use-cache-only` sur `ohlc_daily_BTC.json` (généré 2026-05-19). Stablecoins : `--ohlc-source binance-public` (RUN_LOG.md) — **sources OHLC incohérentes** entre sprints. Cache unique daté du jour des runs → reproductibilité externe non prouvée. |
| 12 | **Conflits anciens rapports / claims trop fortes** | Phase 6 (`wikipedia_btc_attention`) : 16 events, BH 0/5, return post_7 **−0,96 %**, `economically impossible`. Phase 11 basket : BH 3–5/8 sur vol/volume, verdict **candidate OOS** — changement de design (8 pages, agrégat) **sans hold-out** = sur-ajustement plausible. Leaderboard V2 **non mis à jour** pour Phase 11 → risque de double comptage narratif. |

---

## 1. Sprint calendrier — micro-baselines

**Artefact :** `calendar_micro_baselines.json` · 736 bougies · 5 effets pré-enregistrés.

### Verdicts par effet

| Effect ID | Red team | Raison | Correctif requis |
|-----------|----------|--------|------------------|
| `us_market_open_window` | **WARNING** | 526 events mais BH ne rejette que `volume_ratio` post_1/post_3 (pas `return`) ; placebos same-weekday/shift OK sur return post_7 (p≈0,94 / 1,0) ; turnover 71,5 %, net return post_7 **−0,66 %** après coûts. | Conserver en recherche descriptive uniquement ; exiger signal **return** BH + placebo avant toute OOS ; abaisser turnover ou élargir fenêtre horaire (intraday) si l’hypothèse est session US. |
| `sunday_us_evening` | **FAIL** | **Duplication exacte** avec `monday_asia_open` (105 events, statistiques identiques bit-à-bit) sur bougies daily UTC — deux labels, un seul échantillon. | Supprimer l’un des deux effets ou passer à une granularité horaire ; re-pré-enregistrer avant re-run. |
| `monday_asia_open` | **FAIL** | Idem — alias du dimanche ET sur daily OHLC. | Idem. |
| `third_friday` | **FAIL** | n=25 ; BH 0/8 ; gross post_7 0,62 % < coûts 1 % ; placebos non significatifs mais puissance insuffisante. | n≥60 mois d’historique ou abandon ; ne pas interpréter le volume_ratio raw p≈0,01 sans BH. |
| `month_end` | **FAIL** | n=24 ; return post_7 moyen **−0,47 %** ; BH 0/8 ; rejet économique. | Archiver ; pas de OOS. |

### Verdict sprint calendrier : **FAIL**

Le RUN_LOG conclut correctement « aucun effet en candidate OOS » — le red team **confirme**. La duplication Sunday/Monday est une **erreur de design** (granularité daily + fuseaux) qui invalide deux entrées du registre pré-enregistré.

---

## 2. Sprint stablecoins — P9-SC-001-PR

**Artefacts :** `p9-sc-001-pr-{7d,30d}-{low,high}.json` · 366 lignes supply · fenêtre 365 j.

### Verdicts par preregistration

| ID | Red team | Raison | Correctif requis |
|----|----------|--------|------------------|
| P9-SC-001-PR-30d-high | **FAIL** | 0 events → `blocked` (cohérent). Expansion z≥+1,0 inexistante sur la fenêtre. | Documenter impossibilité structurelle ; ne pas retenter sans changement de métrique (flows vs stock). |
| P9-SC-001-PR-7d-high | **FAIL** | n=12 ; BH 1 cellule BTC return post_7 seulement ; `placebo_pass: false` (shift +30j **survit**, wrong-direction lag **survit**) ; ETH sans BH return. | Kill malgré p raw ; n≥30 + placebos shift/lag stricts sur la cellule primaire. |
| P9-SC-001-PR-7d-low | **FAIL** | n=36 ; BH 2–3 cellules BTC+ETH ; **`placebo_pass: false`** (shift +30j et lag −7j survivent tous deux) → corrélation spurious / non-causalité. | Exiger `placebo_pass: true` pour toute promotion ; hold-out temporel 50/50 ; tester lag publication DefiLlama. |
| P9-SC-001-PR-30d-low | **FAIL** | n=52 ; BH 3 cellules ; **`placebo_pass: false`** (shift +30j survit sur return post_7 observé −2,81 %) ; effet « contraction » peut être proxy de stress macro concurrent. | Idem + analyse de concentration par mois ; pre-register une seule cellule primaire (return post_7 BTC). |

### Verdict sprint stablecoins : **FAIL**

Le RUN_LOG.md (« aucun seuil n’atteint candidate OOS ») est **validé**. Les rejets BH sur 30d-low / 7d-low sont **non robustes** aux placebos de calendrier — les conserver comme « weak evidence » serait **trop généreux** ; red team recommande **kill** opérationnel.

**Conflit Phase 3/6 :** V2 avait 0 events à z≥1,5 ; Phase 11 à z=1,0 trouve des events — ce n’est **pas** une confirmation OOS, c’est un **abaissement de seuil in-sample**.

---

## 3. Sprint volume shock — P9-MS-023

**Artefact :** `volume_shock_all_365d.json` · 371 bougies cache · 4 variantes.

| Variante | Red team | Raison | Correctif requis |
|----------|----------|--------|------------------|
| `vol_z20_high` | **FAIL** | n=18 ; BH 3/8 (return post_7, vol post_7, max_dd post_7) ; **`shift_return_post_3_p = 1.0`**, **`shuffle_labels_return_post_3_p = 1.0`** ; script `supported` vs `research_verdict: weak evidence` — asymétrie fenêtre post_3 vs post_7. Choc de volume → baisse forward plausible (**reverse causality** / mean-reversion après spike). | Aligner placebos sur **post_7** ; appliquer BH incluant placebos ; exiger n≥40 ; overlay économique explicite ; ne jamais promouvoir sans signal tradable (hypothèse explicite NOT tradable). |
| `vol_z60_high` | **FAIL** | n=16 ; BH 5/8 ; mêmes placebos post_3 à p=1,0 ; même critique. | Idem. |
| `vol_z20_range_compression` | **FAIL** | 0 events → blocked. | Abandon ou assouplir conditions **pré-enregistrées** dans un futur protocole, pas post-hoc. |
| `vol_z20_low_abs_return` | **FAIL** | 0 events → blocked. | Idem. |

### Verdict sprint volume shock : **FAIL**

Le RUN_LOG Phase 11 (weak evidence / blocked) est directionnellement correct, mais le red team **abaisse** le statut : les variantes z-high ne méritent pas « weak evidence » tant que les placebos ne sont pas recalibrés sur les cellules BH-rejetées — traiter comme **kill**.

---

## 4. Sprint Wikipedia basket — scrutin maximal

**Artefact :** `wikipedia_basket_365d.json`  
**Verdict artefact :** `phase11_final_verdict: candidate for further OOS testing`  
**Verdict red team :** **FAIL — révoquer toute mention « candidate OOS »**

### Pourquoi ce sprint doit être tué

1. **Pas d’OOS.** Aucune partition temporelle, aucun registre hold-out, aucun test sur période postérieure à la conception du panier (2026-05-19). L’étiquette « candidate for further OOS testing » décrit une **intention**, pas un **résultat** — la présenter comme succès Phase 11 est une **sur-déclaration**.

2. **Placebos insuffisants.** `shift_30d_vol_heuristic_significant: false` repose sur un seuil fixe `mean > 0.02` sur vol post_3, sans p-value bootstrap comparable au pipeline standard. Placebo non-crypto : même heuristique ; 34 / 22 events non-crypto — **pas de preuve** que le panier crypto est spécifique au-delà du bruit.

3. **Métrique primaire non tradable.** Return post_7 : p≈0,86 (z=1.5) et p≈0,79 (z=2.0), moyenne **négative** (−0,53 % / −0,68 %). Seuls vol et volume_ratio passent BH — **impossible économiquement** pour une stratégie directionnelle ; observation de régime / liquidité seulement.

4. **Concentration temporelle.** z=2.0 : 9/18 events en **août 2025** (50 %), 5/18 en **février 2026** (28 %). Un régime news/crypto local peut expliquer tout le BH — **leave-one-month-out obligatoire** avant tout label positif.

5. **Double comptage / fuite conceptuelle.** Agrégation de 8 pages ; « Cryptocurrency exchange » domine (42–55 hits selon seuil). Spike d’attention sur exchanges ↔ volume BTC élevé **le même jour** : corrélation contemporaine, pas nécessairement prédictivité forward propre.

6. **Conflit Phase 6.** `wikipedia_btc_attention` (Bitcoin seul, 16 events) : BH 0/5, gross return négatif, leaderboard `economically impossible`. Le basket Phase 11 **change la définition** du signal et obtient BH — pattern classique de **multiple testing / specification search** malgré seuils z « pré-enregistrés » (le panier de 8 pages n’était pas la spec Phase 6).

7. **Verdict interne trop laxiste.** `compute_phase11_verdict` promouvoit en « candidate » dès BH≥1 sur métriques vol/volume **sans** exiger robustesse shift/non-crypto par p-value, **sans** overlay économique, **sans** minimum d’events au-delà de 5 (n=18 limite).

| Seuil z | Red team | Raison courte | Correctif requis |
|---------|----------|---------------|------------------|
| 1.5 (n=29) | **FAIL** | BH vol/volume ; return NS ; concentration ; pas d’OOS | Kill ; si recherche continue : split 2024/2025, placebos bootstrap sur vol post_3, overlay coûts, retirer pages redondantes du panier |
| 2.0 (n=18) | **FAIL** | Idem + n plus faible | Idem ; minimum 40 events OOS |

### Verdict sprint Wikipedia : **FAIL**

**Action immédiate :** rétrograder `phase11_final_verdict` à **`weak evidence` au mieux**, **`kill` recommandé** ; ne pas inscrire au leaderboard V2 comme OOS candidate ; aligner avec `RESEARCH_DECISION_BOARD.md` (« Pas re-prioriser BTC » sur AT-011).

---

## 5. Sprint exchange status — deep dive

**Artefact :** `exchange_status_deep_dive_365d.json` · verdict global **`kill`**.

| Variante | Red team | Raison | Correctif requis |
|----------|----------|--------|------------------|
| `unscheduled_incidents` (n=29) | **FAIL** | BH primary 0 ; vol post_3 p≈0,45 ; return secondaire NS ; shift +14j null. | Accepté kill ; documenter que incidents minor Statuspage ≠ choc prix BTC. |
| `scheduled_maintenance` (n=1) | **FAIL** | Sous G0 ; « weak evidence » trop généreux pour n=1. | Forcer verdict `blocked` / `kill` uniforme. |
| `impact_minor` (n=29) | **FAIL** | Idem unscheduled — pas de signal vol. | Kill. |
| `impact_major` / `impact_critical` (n=1) | **FAIL** | n=1 ; inférence impossible. | Kill / blocked. |
| `duration_gt_30m` (n=25) | **FAIL** | BH 0 ; p≈0,16. | Kill. |
| `venue_kraken` (n=23) | **FAIL** | BH 0. | Kill. |
| `venue_coinbase` (n=15) | **FAIL** | BH 0. | Kill. |
| `basket_combined` (n=30) | **FAIL** | BH 0 ; quasi-identique à unscheduled. | Kill. |

### Défaut méthodologique majeur

Le bloc `placebos.random_timestamps` **n’exécute pas** de timestamps aléatoires : il **réutilise** `primary.cells` et `bh_rejected_primary`. Toute conclusion de robustesse fondée sur ce champ est ** invalide**. Les shifts +14j sont souvent `null` (événements perdus après alignement).

### Verdict sprint exchange status : **FAIL** (confirme le `kill` artefact)

Correctif : implémenter un vrai placebo `random_events_from_candles` sur la métrique primaire ; abaisser le plancher d’impact ou élargir la fenêtre si l’hypothèse reste d’intérêt **observationnel** (jamais tradable, comme pré-enregistré).

---

## Matrice récapitulative (pass / warning / fail)

| Sprint | PASS | WARNING | FAIL |
|--------|------|---------|------|
| Calendrier | 0 | 1 (`us_market_open_window`) | 4 (+ sprint global) |
| Stablecoins | 0 | 0 | 4 (+ sprint global) |
| Volume shock | 0 | 0 | 4 (+ sprint global) |
| Wikipedia basket | 0 | 0 | 2 seuils (+ sprint global) |
| Exchange status | 0 | 0 | 9 variantes (+ sprint global) |

**Aucun PASS au niveau sprint.**

---

## Recommandations transversales (obligatoires avant Phase 12)

1. **Harmoniser OHLC** : une source par étude (Kraken vs Binance vs cache) documentée dans chaque JSON ; figer les caches avec hash/commit.
2. **Placebos alignés** : tester la robustesse sur **la même métrique + fenêtre** que la cellule BH primaire.
3. **Corriger exchange status** : placebo `random_timestamps` réel ; ne pas écrire de champs placebo trompeurs.
4. **Calendrier** : retirer ou refondre `sunday_us_evening` / `monday_asia_open` en daily UTC.
5. **Wikipedia** : **interdiction** du libellé « candidate OOS » sans split hold-out explicite dans l’artefact ; ajouter concentration + overlay économique.
6. **Leaderboard** : ne pas fusionner Phase 11 dans V2 sans rebuild `_build_leaderboard.py` ; éviter contradiction avec Phase 6 wiki/stablecoins.
7. **Verdict ladder unique** : `supported` du script ≠ promotion recherche ; seul `research_verdict` / red team compte.

---

## Tests légers exécutés

- Vérification empirique overlap calendrier Sunday ET ≡ Monday Tokyo (736 bougies) : **100 % identique**.
- Analyse concentration timestamps Wikipedia basket (Python ad hoc sur JSON).
- `pytest tests/test_event_study_exchange_status_phase11.py tests/test_signals_wiki_attention.py` : **ERROR** (imports / environnement — tests non bloquants pour ce rapport documentaire).

---

## Références

- `reports/research_runs_phase11/*.json`
- `reports/research_runs_phase11/RUN_LOG_PHASE11.md`, `RUN_LOG.md`
- `reports/ALPHA_RESEARCH_LEADERBOARD_V2.md`
- `reports/RESEARCH_DECISION_BOARD.md`

**Disclaimer red team :** ce document ne valide aucune rentabilité, aucun déploiement live, aucune modification de `config.yaml`. Phase 11 reste **research-only** ; après red team, **0 signal** ne mérite de capital OOS ou paper trading.
