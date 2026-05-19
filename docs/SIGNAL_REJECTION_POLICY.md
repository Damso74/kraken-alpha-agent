# Politique de rejet des signaux — pipeline alpha alternatif

> Critères explicites pour **rejeter** une hypothèse de recherche et
> éviter qu'un artefact statistique ou un trade chanceux ne remonte
> vers `config.yaml` ou le live. **Rejeter = succès** : la machine
> fonctionne quand elle dit « move on ».

## TL;DR (1 paragraphe)

Un signal ne quitte jamais le stade « recherche read-only » tant qu'il
n'a pas passé, **dans l'ordre**, (1) puissance minimale (≥ 5
événements), (2) placebo empirique + Benjamini–Hochberg FDR à 5 %,
(3) robustesse sans dépendance à un seul trade, (4) expectancy nette
**après** frais Kraken conservateurs (0,25 % maker / 0,40 % taker),
(5) confirmation out-of-sample sur une fenêtre jamais vue, (6) turnover
compatible avec une exécution réaliste. Même alors, **aucun branchement
live** sans le triple opt-in existant (`TRADING_MODE=live`,
`LIVE_TRADING=true`, `ALLOW_LIVE_ORDERS=true`). Les event studies
actuels couvrent les étapes (1)–(2) automatiquement via
`compute_verdict` ; les étapes (3)–(6) restent des barres manuelles
documentées ici.

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
| Nombre d'événements alignés | **≥ 5** | `_event_study_common.compute_verdict` ; warning explicite si `< 5` |
| Couverture cache / historique | Fenêtre `[start, end]` complète | Collectors ; gas history ≥ `lookback + 1` jours pour ETH gas |
| Événements OOB | Audit `events_skipped_oob` | `EventStudyResult` — si élevé, élargir `--days` ou le cache OHLC |

**Rejet immédiat** si `< 5` événements : verdict automatique
`weak evidence` (puissance négligeable).

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
| Puissance (aligné G0) | **< 5** événements | `insufficient_evidence` — ne pas analyser la concentration |
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
| G0 `< 5` events | `weak evidence` — stop |
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
- Code : [`scripts/_event_study_common.py`](../scripts/_event_study_common.py) (`compute_verdict`), [`src/research/placebo.py`](../src/research/placebo.py), [`src/research/concentration.py`](../src/research/concentration.py), [`src/risk.py`](../src/risk.py) (triple opt-in)

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
