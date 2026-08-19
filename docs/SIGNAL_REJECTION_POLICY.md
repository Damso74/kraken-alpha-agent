# Politique de rejet des signaux — pipeline alpha alternatif

> Critères explicites pour **rejeter** une hypothèse de recherche et
> éviter qu'un artefact statistique ou un trade chanceux ne remonte
> vers `config.yaml` ou le live. **Rejeter = succès** : la machine
> fonctionne quand elle dit « move on ».

## TL;DR (1 paragraphe)

Un signal ne quitte jamais le stade « recherche read-only » tant qu'il
n'a pas passé, **dans l'ordre**, (1) puissance minimale (**≥ 30
événements**), (2) placebo empirique + Benjamini–Hochberg FDR à 5 %,
(3) robustesse sans dépendance à un seul trade, (4) expectancy nette
**après** frais Kraken conservateurs (0,25 % maker / 0,40 % taker),
(5) confirmation out-of-sample sur une fenêtre jamais vue, (6) turnover
compatible avec une exécution réaliste. Même alors, **aucun branchement
live** sans le triple opt-in existant (`TRADING_MODE=live`,
`LIVE_TRADING=true`, `ALLOW_LIVE_ORDERS=true`). Les event studies
actuels couvrent les étapes (1)–(2) automatiquement via
`compute_verdict` ; les étapes (3)–(6) restent des barres manuelles
documentées ici.

> **Changement Phase 30.** Le plancher de puissance G0 passe de **5** à
> **30** événements, et le pipeline dérivés (Phase 26) — jusqu'ici sans
> aucun test d'inférence — est soumis aux mêmes gates. Voir
> [« Plancher de puissance »](#pourquoi-30-et-pas-5) et
> [« G0–G3 sur le pipeline dérivés »](#g0g3-sur-le-pipeline-dérivés-phase-26).

## Philosophie

| Principe | Implication |
|----------|-------------|
| **Negative result = output valide** | `not supported, move on` est le verdict attendu sur la majorité des hypothèses |
| **Pas de promotion silencieuse** | Aucune entrée dans `config.yaml`, aucun profil `live_*`, aucun gate production sans trace écrite |
| **Frais pessimistes** | Mieux vaut rejeter un edge borderline que le sur-estimer avec des frais optimistes |
| **Séparation recherche / exécution** | `src/signals/` et `src/research/` n'importent jamais `src.execution` |

Ce document **ne garantit aucune rentabilité**. Il fixe des barres de
rejet — pas des promesses de PnL.

---

## Niveaux de gate

```
  Hypothèse formulée
        │
        ▼
  [G0] Puissance & qualité des données
        │
        ▼
  [G1] Event study + placebo + BH-FDR     ← implémenté dans scripts
        │
        ▼
  [G2] Robustesse (single-trade, turnover)
        │
        ▼
  [G3] Expectancy nette post-frais
        │
        ▼
  [G4] Out-of-sample (walk-forward ou hold-out)
        │
        ▼
  [G5] Triple opt-in live (si un jour branché)  ← src/risk.py
```

Un signal **stoppe** au premier gate échoué. Pas de « on reteste avec
un seuil plus permissif » sans reformuler l'hypothèse *a priori*.

---

## G0 — Puissance et données

| Critère | Seuil | Où c'est appliqué |
|---------|-------|------------------|
| Nombre d'événements alignés | **≥ 30** | `derivatives_event_study.MIN_EVENTS_FOR_INFERENCE` (appliqué) ; `_event_study_common.compute_verdict` (`min_events=5`, **à réhausser**) |
| Couverture cache / historique | Fenêtre `[start, end]` complète | Collectors ; gas history ≥ `lookback + 1` jours pour ETH gas |
| Événements OOB | Audit `events_skipped_oob` | `EventStudyResult` — si élevé, élargir `--days` ou le cache OHLC |

**Rejet immédiat** si `< 30` événements : verdict automatique
`weak evidence` (puissance négligeable). Le rejet est imputé à la couche
**puissance**, jamais à l'inférence : sous le plancher **aucune p-value
n'est calculée**, parce qu'un test qu'on n'a pas les moyens de conduire
n'est pas un test qui échoue.

### Pourquoi 30, et pas 5

Le plancher historique de 5 événements était une garde anti-division par
zéro déguisée en critère statistique. Trois raisons de le relever :

1. **Erreur-type.** Sur des rendements crypto 4h dont l'écart-type
   par événement est de l'ordre de 2–3 pp, l'erreur-type de la moyenne
   à n=9 vaut ~1 pp — soit l'ordre de grandeur des « excès » que le
   pipeline dérivés publiait comme signaux (0,15 à 1,5 pp). L'intervalle
   de confiance couvre le zéro et son opposé. À n=30 l'erreur-type tombe
   sous 0,55 pp, ce qui rend le plancher économique G3 (0,80 pp)
   discriminant plutôt que décoratif.
2. **Bootstrap.** La p-value empirique est lissée en `+1/(n_placebos+1)` ;
   sa résolution ne dépend pas de n, mais la statistique observée qu'on
   lui compare, elle, est instable sous 30 observations. Un placebo qui
   « bat » l'observé une fois sur vingt à n=9 ne dit rien.
3. **Cohérence interne.** Les red teams du dépôt exigent n ≥ 30 à 40 sur
   les études équivalentes ; laisser la politique écrite à 5 créait un
   chemin de promotion plus permissif que la revue humaine. 30 est la
   **borne basse** retenue : un signal à 30–40 événements reste
   `weak evidence` dès qu'une autre couche a le moindre doute.

> **Dette connue.** `scripts/_event_study_common.compute_verdict`,
> `src/research/concentration.py` et `src/research/tradeability.py`
> utilisent encore `min_events=5`. Ces appelants sont **non conformes**
> à la présente politique et doivent être alignés sur 30 ; d'ici là,
> tout verdict `supported` produit avec `5 ≤ n < 30` doit être relu
> comme `weak evidence`.

Critères additionnels par signal (docstrings `src/signals/`) :

| Signal | Condition de rejet documentée dans le code |
|--------|---------------------------------------------|
| `stablecoin_supply` | Placebo indistinguable du baseline |
| `wiki_attention` | Non robuste cross-articles ; placebo reproduce le hit-rate |
| `exchange_status` | **< 10 incidents** au tier d'impact choisi |
| `eth_gas_congestion` | Cluster week-end seulement ; échec placebo |
| `calendar_effects` | Effet absent sur hold-out ; un seul pair drive l'agrégat |
| `options_expiry` | Non significatif vs vendredis placebo ; un seul mois drive |
| `btc_mempool` | Spikes alignés sur news/halving in-sample uniquement |

---

## G1 — Placebo et FDR (implémenté)

### Placebo par défaut

Les scripts `event_study_*.py` et `demo_event_study.py` utilisent :

1. **Event study réel** — `run_event_study()` sur les événements du signal.
2. **Placebo** — pour chaque cellule `(metric, window)`, `n_placebos`
   (défaut **200**) tirages de timestamps aléatoires uniformes dans
   l'index des candles (`random_events_from_candles`), même `n_events`.
3. **P-value empirique** — two-sided avec lissage `+1/(n+1)`
   (`empirical_p_value`).
4. **Benjamini–Hochberg** — FDR cible **`α = 0.05`** sur toutes les
   cellules testées (typiquement 6 : 2 métriques × 3 fenêtres).

Autres placebos disponibles dans `src/research/placebo.py` (non câblés
dans les scripts par défaut, utiles en analyse manuelle) :

- `shift_events_in_time` (+30 jours canonique)
- `shuffle_labels`
- `bonferroni_threshold` (sanity check conservateur)

### Verdict automatique (`compute_verdict`)

| Verdict | Signification | Action |
|---------|---------------|--------|
| `not supported, move on` | Aucun rejet BH ; aucune p brute `< 0.05` | **Archiver.** Hypothèse abandonnée. |
| `weak evidence` | `< 5` events **ou** p brute `< 0.05` sans survie BH | **Ne pas promouvoir.** Re-run optionnel avec fenêtre élargie *pré-enregistrée*. |
| `supported` | ≥ 1 cellule rejette H0 sous BH-FDR | **Passer G2–G4** — pas le live. |

> **Attention.** `supported` ≠ « tradeable ». BH sur 6 tests corrélés
> reste un filtre de dépistage univarié sur retours bruts sans frais.

### Direction pré-enregistrée (obligatoire)

Un test d'excès de rendement n'a de sens que **signé**. La direction
attendue (`long` / `short`) doit être fixée **avant** de regarder le
résultat, et un excès de signe opposé est un **rejet**, pas une preuve
plus faible.

| Cas | Décision |
|-----|----------|
| Direction pré-enregistrée, excès de même signe | Continuer vers l'inférence |
| Direction pré-enregistrée, excès de signe opposé | **Rejet** (couche `direction`) — le signal a produit l'inverse de ce qui était prédit |
| Direction **non** pré-enregistrée | **Rejet** (couche `direction`), avec la raison explicite — pas de p-value repêchée en two-sided pour justifier un overlay |

Conséquence directe : un filtre en **valeur absolue** sur l'excès
(`abs(excess) >= seuil`) est interdit. C'était exactement le défaut du
pipeline dérivés avant la Phase 30 (voir ci-dessous), où un excès de
−1,53 pp comptait comme preuve favorable.

Un détecteur symétrique (qui déclenche sur les deux queues d'une
distribution : `|z| >= 2`, percentile `<=10 %` **ou** `>=90 %`) ne peut
pas porter de direction unique. Pour le rendre testable il faut le
**scinder** en deux signaux pré-enregistrés séparément, chacun avec sa
propre direction ; tant que ce n'est pas fait, il reste rejeté en
`direction`.

---

## G0–G3 sur le pipeline dérivés (Phase 26)

Module : [`src/bot/derivatives_event_study.py`](../src/bot/derivatives_event_study.py).
Sorties : `reports/phase26_event_studies/{summary.json,results.csv}`.

### État avant Phase 30 (non conforme)

Ce pipeline vivait **hors** de la présente politique : aucune p-value,
aucun placebo, aucune correction multi-tests, aucun import de
`src/research/placebo.py` ni de `src/research/event_study.py`. Son
unique filtre était `abs(excess_mean_pct) >= 0.15` — un seuil ni
pré-enregistré, ni relié à un coût, ni signé. Résultat : `non_trivial_signals`
comptait des cellules à excès négatif sur 9 à 11 observations, et
`proceed_to_overlay` rendait `true` sur **4 bundles sur 4**.

### État Phase 30 (conforme)

Les mêmes gates que G0–G3, appliqués en **court-circuit** sur chaque
cellule `(signal, horizon)` :

| Couche | Règle | Constante |
|--------|-------|-----------|
| `power` | `n >= 30` événements exploitables ; **aucune p-value calculée** en dessous | `MIN_EVENTS_FOR_INFERENCE` |
| `direction` | direction pré-enregistrée dans `EventStudySpec.expected_direction`, et excès du bon signe | `expected_direction` / `direction_note` |
| `inference` | p-value bootstrap par ré-ancrage aléatoire (`run_placebo_bootstrap`, 200 réplicats seedés) puis **Benjamini–Hochberg à α = 0,05 sur la famille du bundle entier** (jusqu'à 18 tests : 6 signaux × 3 horizons) | `DEFAULT_N_PLACEBOS`, `DEFAULT_FDR_ALPHA` |
| `economic` | `abs(excess) >= 0,80 pp`, le round-trip taker G3 — et non 0,15 pp | `ECONOMIC_EXCESS_FLOOR_PCT` |

La famille BH est le **bundle entier**, pas un signal isolé : les 18
tests sont menés simultanément sur le même actif et la même série de
prix ; corriger signal par signal reviendrait à ne pas corriger.

Le verdict n'est plus un booléen opaque. `classify_event_study_verdict_detail`
et chaque cellule de `forward_stats` exposent :

- `gate_rejected_by` — la **première** couche qui rejette (`power` /
  `direction` / `inference` / `economic`) ;
- `gate_reason` — la raison chiffrée (`n=9 < power floor 30`, `excess
  -1.5251 pp contradicts the pre-registered long direction`, …) ;
- `gate_layers` — l'état de chaque couche (`pass` / `fail` / `n/a`,
  `n/a` signifiant « non évaluée, court-circuit amont ») ;
- `rejection_breakdown` au niveau du bundle — le compte de rejets par
  couche.

### Direction : aucun signal Phase 26 n'est éligible aujourd'hui

Les six détecteurs actuels sont **tous symétriques** (`funding_extreme`
sur les deux queues, `funding_zscore` sur `|z|`, `funding_oi_disagreement`
sur les deux polarités) ou portent une hypothèse de **volatilité** et non
de direction (`oi_expansion_flat_price`, `oi_zscore_range_compress`).
Leur `expected_direction` vaut donc `None` et le pipeline le déclare
explicitement au lieu de laisser passer n'importe quel signe. Les
débloquer suppose de les scinder et de pré-enregistrer chaque moitié —
travail de recherche, pas de plomberie.

### Effet sur les verdicts publiés

En rejouant les gates déterministes (`power`, `direction`) sur
`reports/phase26_event_studies/summary.json` :

| Bundle | Publié | Après gates |
|--------|--------|-------------|
| BTC 4h | `non_trivial=4`, `proceed=true`, `overlay_only` | `non_trivial=0`, `proceed=false`, **`weak`** (6 rejets `power`, 6 `direction`) |
| BTC 1d | `non_trivial=2`, `proceed=true`, `blocked_data` | `non_trivial=0`, `proceed=false`, `blocked_data` (inchangé : `oi_rows=30 < 100`) |
| ETH 4h | `non_trivial=3`, `proceed=true`, `overlay_only` | `non_trivial=0`, `proceed=false`, **`weak`** (6 rejets `power`, 6 `direction`) |
| ETH 1d | `non_trivial=2`, `proceed=true`, `blocked_data` | `non_trivial=0`, `proceed=false`, `blocked_data` (inchangé) |

Aucune couche `inference` ni `economic` n'est atteinte : tout est rejeté
en amont. C'est le résultat attendu — **rejeter = succès**.

---

## G2 — Robustesse

### Pas de dépendance à un seul trade

**Rejet** si, après retrait du événement ayant le plus grand
contribution au `mean` post-event :

- le signe du `mean` s'inverse, **ou**
- `|mean|` chute de plus de **50 %**, **ou**
- `n_positive / n_events` (hit-rate) repasse sous **50 %** sur la
  fenêtre principale (`post_7` par convention).

Méthode recommandée : jackknife leave-one-event-out sur la série des
retours par événement (non automatisé dans les scripts actuels).

### Turnover / fréquence d'activation

**Rejet** si la stratégie dérivée du signal impliquerait :

- plus d'**1 rotation complète** (entrée + sortie) par jour calendaire
  en moyenne sur la fenêtre de test, **ou**
- un taux d'événements **> 30 %** des candles (signal trop bruyant
  pour être un « événement » distinct).

Les scripts event study affichent déjà
`len(events) / len(candles)` — utiliser ce ratio comme heuristique
(`> 0.30` → rejet G2).

### G2b — Risque de concentration (implémenté)

Module : [`src/research/concentration.py`](../src/research/concentration.py).
Rapport de référence : [`reports/CONCENTRATION_RISK.md`](../reports/CONCENTRATION_RISK.md).

Après un event study, construire une série **par événement** de contributions
(ex. retour forward `post_7` par événement, ou slice de PnL attribuable) et
appeler `classify_concentration_risk(contributions, event_months=…)` ou
`event_timestamps=…` (mois dérivés en UTC `YYYY-MM`).

| Règle | Seuil | Verdict si échec |
|-------|-------|------------------|
| Puissance (aligné G0) | **< 5** événements dans le code ; **< 30** selon la présente politique (dette listée en G0) | `insufficient_evidence` — ne pas analyser la concentration |
| Un seul événement | part **> 20 %** de `sum(abs(·))` | `high_concentration_risk` |
| Top 3 événements | part combinée **> 50 %** | `high_concentration_risk` |
| Un mois calendaire | part **> 40 %** | `high_concentration_risk` |
| Aucune règle ci-dessus, N ≥ 5 | — | `acceptable` (poursuivre G3–G4) |

Les comparaisons sont **strictes** (`>`) : 20 % / 50 % / 40 % exacts ne
déclenchent pas le rejet. Les parts utilisent les **valeurs absolues** au
numérateur pour ne pas masquer un outlier par compensation signée.

**Rejet G2** si `verdict == "high_concentration_risk"` — documenter les
`reasons` retournées. **Stop** si `insufficient_evidence` (même logique que
G0). Ce filtre est **complémentaire** au jackknife leave-one-event-out
ci-dessus ; les deux peuvent être exécutés sur la même série.

---

## G3 — Expectancy nette (frais Kraken conservateurs)

Les métriques `return` de l'event study sont **brutes** (pas de frais).
Toute promotion exige une couche de coûts explicite.

### Hypothèse de frais (conservative, non négociable pour cette politique)

| Côté | Taux | Usage |
|------|------|-------|
| Maker | **0,25 %** (25 bps) par jambe | Scénario optimiste d'exécution |
| Taker | **0,40 %** (40 bps) par jambe | **Scénario par défaut** pour la barre de rejet |

Round-trip taker conservateur : **0,80 %** (achat + vente).

### Barre de rejet

**Rejet G3** si, sur la fenêtre de référence (`post_7` daily) :

```text
mean_return_brut − 0.008  <  0
```

c'est-à-dire expectancy nette **≤ 0** après soustraction du round-trip
taker 0,80 %. Si le brut est positif mais `< 0,80 %`, le signal est
classé **« edge illusoire »** — rejet.

Pour un signal vol-only (`realized_vol`), G3 s'applique seulement si
une règle de trading concrète (straddle, fade, etc.) a été
**pré-enregistrée** avec ses frais propres.

> Le simulateur paper local utilise parfois `fee = size × 0.001` (10 bps)
> dans `src/execution.py` — **plus optimiste** que cette politique.
> Ne pas utiliser ce chiffre pour valider un signal alternatif.

---

## G4 — Out-of-sample (OOS)

L'event study in-sample **ne suffit pas**. Alignement avec la discipline
du [`METHODOLOGY.md`](METHODOLOGY.md) :

### Minimum pour considérer une suite de tests

| Exigence | Détail |
|----------|--------|
| Split temporel | Train / test sans chevauchement ; le test **n'a pas servi** au choix des seuils z / impact / article |
| Filtre OOS walk-forward (moteur principal, référence) | `test net_pnl_usd ≥ 0` ET `test win_rate ≥ seuil preset` ET `trades_count` plancher — cf. presets crypto dans METHODOLOGY |
| Pour signaux alternatifs (event study) | Reproduire le **même** signal + seuils sur la portion test ; exiger survie BH-FDR **ou** p empirique `< 0.05` **sur le test seul** |
| Échec OOS | **Rejet définitif** pour cette variante paramétrique ; pas de retuning sur le test |

Un signal qui ne passe qu'in-sample rejoint le pattern documenté
**0 / 48** (xStocks) et **0 / 144** (crypto walk-forward) : comportement
sain du repo, pas un bug.

---

## G5 — Live : triple opt-in (non négociable)

Même un signal qui aurait passé G0–G4 **ne déclenche aucun ordre**
sans les trois flags simultanés vérifiés par `src/risk.evaluate_risk` :

```text
TRADING_MODE=live
LIVE_TRADING=true
ALLOW_LIVE_ORDERS=true
```

Re-vérification ceinture-et-bretelles dans `src/execution.py` mode
`live`. Le pipeline alpha alternatif **n'active pas** ces flags et
**ne modifie pas** `config.yaml`.

État actuel documenté ailleurs : **0 profil `live_crypto_*` promu**
 après walk-forward et Optuna (cf. METHODOLOGY, OPTION_D_ACTIVATION).

---

## Matrice de décision synthétique

| Gate | Échec → |
|------|---------|
| G0 `< 30` events | `weak evidence` — stop, rejet imputé à **puissance** |
| G1 direction non pré-enregistrée ou signe contraire | `weak evidence` — stop, rejet imputé à **direction** |
| G1 pas de rejet BH, p ≥ 0.05 | `not supported, move on` — **succès** |
| G1 `supported` mais G2 / G2b fail | Rejet manuel — documenter |
| G3 expectancy nette ≤ 0 (frais taker) | Rejet — edge illusoire |
| G4 OOS fail | Rejet — ne pas retuner sur le test |
| G5 triple opt-in absent | Live impossible par design |

---

## Ce que cette politique n'autorise **pas**

- Modifier `config.yaml` ou créer un profil live sur la base d'un seul
  event study `supported`.
- Présenter un hit-rate in-sample comme preuve de PnL futur.
- Ignorer les frais parce que le brut est « presque » positif.
- Utiliser le live pour « tester » un signal alternatif — la recherche
  reste read-only jusqu'à validation OOS séparée.

---

## Références croisées

- [`ALTERNATIVE_ALPHA_PIPELINE.md`](ALTERNATIVE_ALPHA_PIPELINE.md) — architecture et scripts
- [`DATA_SOURCES.md`](DATA_SOURCES.md) — limites des feeds (gas history, sparse incidents)
- [`METHODOLOGY.md`](METHODOLOGY.md) — walk-forward OOS du moteur principal
- Code : [`scripts/_event_study_common.py`](../scripts/_event_study_common.py) (`compute_verdict`), [`src/research/placebo.py`](../src/research/placebo.py), [`src/research/concentration.py`](../src/research/concentration.py), [`src/bot/derivatives_event_study.py`](../src/bot/derivatives_event_study.py) (gates dérivés Phase 30), [`src/risk.py`](../src/risk.py) (triple opt-in)

---

## G3 automatisé — modèle de coûts recherche (Phase 7)

À partir de la Phase 7, la barre G3 peut être appliquée via
`src/research/cost_model.py` et `src/research/tradeability.py` (stdlib
uniquement, **sans** import `execution` / `risk` / `backtest`).

### Fonctions

| Fonction | Usage |
|----------|--------|
| `estimate_round_trip_cost` | Frais taker/taker 0,80 % + spread pessimiste (majors 0,20 %, alts 0,60 %) |
| `compute_net_event_return` | `gross_mean − cost` sur la fenêtre de référence |
| `reject_if_cost_dominated` | Rejet booléen + raison pour rapports / leaderboard |
| `classify_tradeability` | Verdict structuré (voir ci-dessous) |
| `summarize_cost_assumptions` | Snapshot des constantes pour audit |

### Verdicts (`classify_tradeability`)

| Verdict | Rejet G3 ? | Live ? |
|---------|------------|--------|
| `economically impossible` | Oui (brut < **0,50 %** par trade — suspect) | **Jamais** |
| `cost dominated` | Oui (net ≤ 0 après coûts pessimistes) | **Jamais** |
| `research only` | Non (suivre G2/G4 manuellement) | **Jamais** |
| `candidate for paper observation` | Non (paper **observation** uniquement) | **Jamais** |

> **Rappel.** Même `candidate for paper observation` n'ouvre aucun chemin
> live. Le triple opt-in G5 reste obligatoire et hors scope du pipeline
> alpha alternatif.

Détail des hypothèses et exemples : [`reports/ECONOMIC_REALISM.md`](../reports/ECONOMIC_REALISM.md).
