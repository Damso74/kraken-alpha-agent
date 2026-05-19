# Pipeline alpha alternatif — machine à rejeter des hypothèses

> Document compagnon post-hackathon. Décrit le pipeline de recherche
> **read-only** (collectors → signaux → event study → placebo → verdict
> BH-FDR). Ce pipeline **n'est pas** du trading live et **ne prétend pas**
> produire de l'alpha exploitable — il existe pour éliminer vite les
> fausses pistes.

## TL;DR (1 paragraphe)

Le pipeline alpha alternatif assemble des feeds publics (DefiLlama,
Wikimedia, Etherscan, Statuspage, OHLC Kraken REST), les transforme
en timestamps d'événements via `src/signals/`, mesure le comportement
abnormal du prix autour de ces événements avec `src/research/event_study.py`,
puis falsifie le résultat avec des placebos et une correction
Benjamini–Hochberg dans `src/research/placebo.py` et
`scripts/_event_study_common.py`. Le verdict attendu sur la plupart des
hypothèses est **`not supported, move on`** — c'est un **succès**
méthodologique, pas un échec de projet. Aucune branche de ce pipeline
n'importe `src.execution`, `src.risk` ou `src.futures_kraken_cli`.

## Philosophie « honest-negative »

Trois principes guident ce travail :

1. **Rejeter tôt.** Une hypothèse qui ne survit pas placebo + FDR sur
   une fenêtre courte ne mérite pas un walk-forward coûteux ni une
   modification de `config.yaml`.
2. **Conserver les non-résultats.** Comme pour le walk-forward documenté
   dans [`METHODOLOGY.md`](METHODOLOGY.md) (0/48 survivors xStocks,
   0/144 crypto), un pipeline qui dit « non » honnêtement vaut mieux
   qu'un grid search qui trouve un gagnant in-sample.
3. **Pas de promesse de PnL.** Les event studies mesurent des
   distributions de retours/volatilité autour d'événements ; ils ne
   modélisent ni frais Kraken, ni slippage, ni exécution. Voir
   [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md) pour les
   barres de promotion au-delà de ce stade.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  COUCHE 1 — Collectors (HTTP read-only, cache JSON)                         │
│  src/data/collectors/                                                       │
│    defillama │ wikimedia │ etherscan │ status_pages │ _common               │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ rows normalisés {timestamp, …}
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  COUCHE 2 — Signaux (rows → list[int] timestamps UTC)                       │
│  src/signals/                                                               │
│    stablecoin_supply │ wiki_attention │ exchange_status │ eth_gas_congestion│
│    calendar_effects │ options_expiry │ btc_mempool (+ _stats rolling z)     │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ events (+ alignement sur candles journalières)
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  COUCHE 3 — Prix de référence (OHLC journalier, Kraken REST public)         │
│  src/crypto_ohlc_rest.py  ←  fetch_daily_ohlc() dans scripts                │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ candles + events
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  COUCHE 4 — Event study (stdlib only)                                       │
│  src/research/event_study.py → run_event_study()                            │
│    fenêtres post_1 / post_3 / post_7 │ métriques return, realized_vol       │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ mean par (metric, window) + baseline
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  COUCHE 5 — Placebo + FDR                                                     │
│  src/research/placebo.py                                                    │
│    random_events_from_candles (N=200 par défaut) → empirical_p_value        │
│    benjamini_hochberg (α=0.05) sur toutes les cellules                        │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                ▼
                    VERDICT (compute_verdict)
         supported │ weak evidence │ not supported, move on
```

### Contrat de sécurité (identique à `src/research/__init__.py`)

| Règle | Détail |
|-------|--------|
| Read-only | Aucun ordre, aucune clé Kraken requise pour les scripts event study |
| Stdlib dans `src/research/` | Pas de pandas/numpy dans event_study ni placebo |
| Déterministe | Seed explicite (`--seed`, défaut `20260519`) pour les placebos |
| Pas de mutation venue | Interdit d'importer execution / risk / futures_kraken_cli |

## Composants

| Composant | Fichier | Rôle |
|-----------|---------|------|
| Event study engine | [`src/research/event_study.py`](../src/research/event_study.py) | Agrège retour, vol réalisée, volume ratio, max drawdown par fenêtre |
| Placebo / FDR | [`src/research/placebo.py`](../src/research/placebo.py) | Shift temporel, tirage aléatoire, shuffle, BH, p-value empirique |
| Collectors | [`src/data/collectors/`](../src/data/collectors/) | Feeds HTTP + cache sous `data/collector_cache/` |
| Signaux | [`src/signals/`](../src/signals/) | Z-scores roulants, calendrier, incidents → timestamps |
| OHLC crypto | [`src/crypto_ohlc_rest.py`](../src/crypto_ohlc_rest.py) | REST public `https://api.kraken.com/0/public/OHLC` |
| Harness CLI | [`scripts/_event_study_common.py`](../scripts/_event_study_common.py) | Args communs, placebo bootstrap, verdict, export JSON |
| Demo F&G | [`scripts/demo_event_study.py`](../scripts/demo_event_study.py) | Démo end-to-end Fear & Greed (hors collectors, via `external_signals`) |

### Métriques et fenêtres par défaut

Les scripts `event_study_*.py` utilisent les constantes de
`_event_study_common.py` :

- **Fenêtres** : `post_1`, `post_3`, `post_7` (candles strictement
  post-événement, résolution journalière = 1, 3 et 7 jours).
- **Métriques** : `return` (arithmétique close-first → close-last),
  `realized_vol` (écart-type des log-returns intra-fenêtre).
- **Baseline** : moyenne glissante de la même métrique sur toutes les
  ancres admissibles (`compute_baseline=True`).
- **Placebos** : `200` réplicats par défaut ; chaque réplicat tire
  `n_events` timestamps uniformément dans l'index des candles.
- **FDR** : Benjamini–Hochberg à `α=0.05` sur les p-values empiriques
  two-sided de chaque cellule `(metric, window)`.

### Verdict automatique (`compute_verdict`)

| Condition | Verdict |
|-----------|---------|
| `< 5` événements alignés | `weak evidence` |
| ≥ 1 cellule rejetée par BH-FDR | `supported` |
| Aucun rejet BH mais ≥ 1 p brute `< 0.05` | `weak evidence` |
| Sinon | `not supported, move on` |

Le verdict `supported` signifie « survit le filtre FDR sur cette fenêtre
**univariée** » — pas « prêt pour le live ». Voir la politique de
rejet complète dans [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md).

## Scripts disponibles

Tous les scripts ci-dessous sont **read-only** : pas de modification de
`config.yaml`, pas d'appel à l'agent loop.

### Démo de référence (Fear & Greed)

Hypothèse volontairement faible : « F&G extrême → retour positif 7j ».
Attendu : échec BH sur BTC/180j — sert de tutoriel du harness.

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/demo_event_study.py
python scripts/demo_event_study.py --days 90 --fear-threshold 30
python scripts/demo_event_study.py --use-cache-only --json-out data/demo_event_study.json
```

Source signal : [`src/external_signals.fetch_fear_greed`](../src/external_signals.py)
(cache `data/external_cache/fear_greed.json`, pas un collector DefiLlama).

### Event studies par hypothèse alternative

| Script | Signal | Ticker défaut | Feed externe |
|--------|--------|---------------|--------------|
| [`event_study_stablecoins.py`](../scripts/event_study_stablecoins.py) | Expansion/contraction supply 7j (z-score) | BTC | DefiLlama |
| [`event_study_wikipedia.py`](../scripts/event_study_wikipedia.py) | Pic ou creux d'attention pageviews | BTC | Wikimedia |
| [`event_study_exchange_status.py`](../scripts/event_study_exchange_status.py) | Incidents Statuspage | BTC | Kraken / Coinbase |
| [`event_study_eth_gas.py`](../scripts/event_study_eth_gas.py) | Congestion gas ETH (fast gwei z-score) | ETH | Etherscan (+ history cache) |
| [`event_study_calendar.py`](../scripts/event_study_calendar.py) | Frontières calendrier / session | BTC | Aucun (timestamps OHLC) |
| [`event_study_deribit_expiry.py`](../scripts/event_study_deribit_expiry.py) | 3e vendredi mensuel (calendrier pur — **pas d'API Deribit**) | BTC | Aucun — **expérimental** |

Arguments communs (tous les `event_study_*.py` sauf demo) :

```text
--days 180          Fenêtre look-back (défaut 180)
--ticker BTC        Paire crypto Kraken REST
--n-placebos 200    Réplicats placebo
--seed 20260519     Graine maître
--alpha 0.05        FDR Benjamini-Hochberg
--use-cache-only    Pas de HTTP sur les feeds signaux (cache requis)
--output-json PATH  Export JSON du rapport complet
```

Exemples :

```powershell
python scripts/event_study_stablecoins.py --direction high --z-threshold 1.5
python scripts/event_study_wikipedia.py --article Ethereum --mode momentum
python scripts/event_study_exchange_status.py --venue kraken --min-impact major
python scripts/event_study_eth_gas.py --use-cache-only --history-cache data/collector_cache/etherscan_gas_history.json
python scripts/event_study_calendar.py --calendar-flag weekend_start --ticker ETH
python scripts/event_study_deribit_expiry.py --ticker BTC --output-json data/deribit_expiry_report.json
```

### Alignement événements ↔ candles

Les feeds journaliers (DefiLlama, Wikimedia, supply) produisent des
timestamps UTC ; `_event_study_common.align_events_to_daily_candles`
les projette sur la candle journalière Kraken du même jour civil.
Les signaux calendrier (`calendar`, `deribit_expiry`) s'ancrent
directement sur les timestamps OHLC.

### Expiry « Deribit » — honnêteté feed

`event_study_deribit_expiry.py` **n'appelle pas Deribit**. Il marque les
3e vendredis UTC via `options_expiry.py` et mesure retour/vol forward
sur OHLC Kraken. Aucun collector open interest / prix options n'existe
dans `src/data/collectors/`. Traiter ce script comme **expérimental /
cache-only** (aucun cache requis — calendrier dérivé des candles) :
motivation hypothétique, pas un pipeline options « ready ».

## Relation avec le reste du repo

| Pipeline | Objectif | Doc |
|----------|----------|-----|
| **Alpha alternatif** (ce document) | Tester des hypothèses exogènes cheaply | — |
| Walk-forward xStocks / crypto | Optimiser les seuils du moteur existant | [`METHODOLOGY.md`](METHODOLOGY.md) |
| Optuna + signaux externes | Élargir l'espace param + gates F&G / BTC dom | [`STRATEGY_DISCOVERY_REPORT.md`](STRATEGY_DISCOVERY_REPORT.md) |
| Live agent | Exécution triple opt-in | [`README.md`](../README.md) § Safety |

Le pipeline alpha alternatif **ne remplace pas** le walk-forward : au
mieux, une hypothèse `supported` ici justifie un test OOS séparé — pas
une promotion directe en production.

## Tests de régression

| Suite | Fichier |
|-------|---------|
| Event study (métriques, fenêtres, agrégats) | [`tests/test_event_study.py`](../tests/test_event_study.py) |
| Placebo / BH / p-value empirique | [`tests/test_placebo.py`](../tests/test_placebo.py) |
| Collectors | `tests/test_collectors_*.py` |
| Signaux | `tests/test_signals_*.py` |

```powershell
pytest tests/test_event_study.py tests/test_placebo.py tests/test_collectors_*.py tests/test_signals_*.py
```

## Caveats explicites

1. **Résolution journalière.** Les scripts event study utilisent des
   candles 1440-min. Les effets intra-day (session US, gas spikes
   horaires) sont lissés.
2. **Pas de frais dans l'event study.** Les métriques `return` sont
   brutes ; toute barre de promotion doit soustraire les frais
   conservateurs Kraken (voir politique de rejet).
3. **Etherscan gas = snapshot only.** L'oracle Etherscan ne fournit qu'un
   instantané HTTP ; l'historique journalier est un cache local append-only
   (`etherscan_gas_history.json`, minimum `lookback + 1` rows). Pas de
   backfill API officiel dans ce repo. `--use-cache-only` sans history →
   `blocked: missing historical gas cache`. Schéma d'exemple SYNTHETIC :
   [`data/collector_cache/examples/`](../data/collector_cache/examples/).
   Voir [`DATA_SOURCES.md`](DATA_SOURCES.md) et
   [`data/collector_cache/README.md`](../data/collector_cache/README.md).
4. **Deribit expiry = calendrier seulement.** `event_study_deribit_expiry.py`
   n'a pas de feed Deribit ; test expérimental sur 3e vendredi UTC.
5. **FDR ≠ causalité.** Survivre BH sur 6 cellules corrélées n'établit
   pas un lien causal ; c'est un filtre de dépistage, pas une preuve
   d'edge tradeable.
6. **Signaux non branchés au live.** `src/signals/` alimente uniquement
   la recherche ; les gates production (Fear & Greed, BTC dominance,
   vol regime) restent dans `src/external_signals.py`.

## Références croisées

- [`HYPOTHESIS_BACKLOG_PHASE_9.md`](HYPOTHESIS_BACKLOG_PHASE_9.md) — backlog 100 hypothèses (docs only)
- [`WEIRD_BUT_TESTABLE_SIGNALS.md`](WEIRD_BUT_TESTABLE_SIGNALS.md) — sous-ensemble weird falsifiable
- [`DATA_SOURCES.md`](DATA_SOURCES.md) — APIs, caches, limites connues
- [`data/collector_cache/README.md`](../data/collector_cache/README.md) — inventaire cache + refresh gas history
- [`SIGNAL_REJECTION_POLICY.md`](SIGNAL_REJECTION_POLICY.md) — critères
  de rejet et barres de promotion
- [`METHODOLOGY.md`](METHODOLOGY.md) — walk-forward et honnêteté OOS
  sur le moteur principal
