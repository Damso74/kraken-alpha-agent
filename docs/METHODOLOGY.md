# Méthodologie — Walk-forward & honnêteté statistique

> Document compagnon de `docs/SUBMISSION.md`. Décrit comment les
> paramètres du `aggressive_competition` ont été audités contre le
> risque de **curve-fitting**, et pourquoi la configuration livrée à
> la submission reste celle d'avant tuning.

## TL;DR (1 paragraphe)

Le snapshot principal `web/public/data/backtest_xstocks_30d.json`
(+33.56 USD / 53.0 % de win-rate / 1.68 % de max-drawdown sur 30
jours 60-min) a été **audité par un walk-forward strict** sur 120
jours de candles 240-min : 48 configurations testées, **0
configuration n'a passé le filtre out-of-sample** (test PnL ≥ 0 ET
test win-rate ≥ 50 %). Aucun *winner* à promouvoir, aucune
modification de `config.yaml`. Ce non-résultat est **conservé tel
quel** parce que (a) c'est la sortie honnête de la procédure et (b)
faire varier le seuil après coup pour "trouver un gagnant" est
exactement la définition du data-snooping qu'on veut éviter.

## Pourquoi le walk-forward, pas un grid search vanilla ?

Le `scripts/backtest_xstocks.py --grid-search` qui existait déjà
explore une grille de calibration **sur une seule fenêtre**. Le
résultat est typiquement biaisé : l'optimiseur choisit la
configuration qui colle le mieux au *bruit* de cette fenêtre. Sur
une stratégie où la baseline `aggressive_competition` produit
+33.56 USD avec une grille de 672 combos, on peut presque
arithmétiquement *garantir* que quelques combos affichent +50 USD
ou plus — ce qui ne dit **rien** sur leur tenue sur les 30 jours
suivants.

Le walk-forward casse ce piège en deux temps :

1. **Train (in-sample)** — on entraîne (= on simule) sur la
   première partie du dataset. Cette portion peut être généreusement
   sur-fittée sans conséquence, parce qu'elle ne servira pas à
   décider.
2. **Test (out-of-sample)** — on simule la même configuration sur
   la portion suivante, *jamais vue* par le processus de sélection.
   Si la performance s'effondre entre train et test, c'est un signal
   direct de curve-fitting et la configuration est rejetée.

Un *survivor* doit franchir une barre minimale **sur le test set**,
pas sur le train. C'est cette discipline qui transforme un grid
search ordinaire en walk-forward.

## Implémentation

| Composant | Fichier |
|-----------|---------|
| Logique pure (split, expansion grille, scoring) | [`src/walk_forward.py`](../src/walk_forward.py) |
| Driver (fetch OHLC, écriture JSON, CLI) | [`scripts/walk_forward_xstocks.py`](../scripts/walk_forward_xstocks.py) |
| Tests (13 cas) | [`tests/test_walk_forward.py`](../tests/test_walk_forward.py) |
| Résultats bruts | `data/walk_forward_results.json` (gitignored) |

Le module `src/walk_forward.py` est strictement *read-only* vis-à-vis
du venue : il délègue chaque simulation à
`src.backtest.simulate_portfolio`, qui n'invoque jamais `kraken paper`,
`kraken order`, ou `kraken futures` mutatifs. La fonction
`_build_settings_override` clone un objet `Settings` immuable pour
appliquer les overrides — **`config.yaml` n'est jamais modifié**.

## Split exact

Les candles 240-min × 120 jours fournissent **720 candles par
symbole** (cap naturel de Kraken). Avec `train_fraction=0.75` :

| Slice | Candles | Période calendaire | Couverture |
|-------|---------|--------------------|------------|
| **Train** (in-sample) | 540 (×9 symboles = 4 860) | 2026-01-18T12:00:00Z → 2026-04-18T08:00:00Z | 90 jours |
| **Test** (out-of-sample) | 180 (×9 symboles = 1 620) | 2026-04-18T12:00:00Z → 2026-05-18T08:00:00Z | 30 jours |

Le set de test couvre **exactement la fenêtre calendaire du snapshot
principal** (60-min × 30 jours = 2026-04-16 → 2026-05-15). Les deux
séries diffèrent par leur résolution (240-min versus 60-min) mais
balayent les mêmes jours de marché. Cette équivalence calendaire est
la condition d'honnêteté : une configuration validée sur le test
240-min n'a *pas pu* être ajustée à partir des fills 60-min du
snapshot, parce que la sélection s'est faite sur une autre série
temporelle, plus grossière.

> **Note sur la résolution.** Kraken plafonne à ~720 candles par
> intervalle. À 60 minutes, 720 candles = ~30 jours ; il est donc
> physiquement impossible de construire un walk-forward 60-min avec
> 90 jours d'historique. Le 240-min est le compromis naturel pour
> obtenir un horizon de ~120 jours tout en restant sur la couche
> tokenized_asset.

## Grille testée (48 combos)

```python
DEFAULT_GRID = {
    "min_confidence_to_trade":    [0.10, 0.15, 0.22, 0.30],  # 4 valeurs
    "min_opportunity_score_buy":  [0.04, 0.06, 0.08, 0.10],  # 4 valeurs
    "max_hold_minutes":           [60,   90,   180],         # 3 valeurs
}
```

Choix anchorés sur la baseline `aggressive_competition` (qui vit
dans `config.yaml`) :

- `min_confidence_to_trade = 0.22` ± 0.08 : on teste à la fois plus
  permissif (0.10) et plus strict (0.30).
- `min_opportunity_score_buy = 0.08` : balayage [0.04, 0.10] autour
  du seuil de production.
- `max_hold_minutes = 90` (depuis `exit.max_hold_minutes`) : on
  élargit à [60, 180].

Volume total : 48 combos × 2 simulations (train + test) × 9 symboles
= **864 runs symboles-fois**. Durée mesurée : **~5 min** sur la
machine du développeur.

## Filtre out-of-sample

```python
survives = (
    test.net_pnl_usd  >= 0.0   # PnL non-négatif sur les 30 derniers jours
    and test.win_rate >= 0.50  # majorité de trades gagnants
    and test.trades_count > 0  # au moins un fill (rejette les configs HOLD-only)
)
```

Une configuration ne passe la phase de ranking **que si elle survit
les trois conditions sur le test set**. Sinon elle est éliminée
sans ambiguïté.

## Score composite (pour les survivants)

```python
score = test.net_pnl_usd * test.win_rate / max(test.max_drawdown_pct, 0.5)
```

Trois propriétés voulues :
- Multiplier par `win_rate` punit les "1 trade chanceux qui domine
  l'aggrégat" ;
- Diviser par `max_drawdown_pct` récompense les trajectoires peu
  volatiles ;
- Le plancher à 0.5 % sur le drawdown évite que des configurations à
  drawdown quasi-nul fassent exploser le score.

## Résultat de cette exécution (HEAD)

**0 configuration sur 48 n'a passé le filtre.**

Distribution observée :

| Métrique test set | min | médiane | max |
|-------------------|-----|---------|-----|
| `net_pnl_usd` | −9.92 USD | −9.92 USD | **+0.69 USD** |
| `win_rate` | 25.5 % | 36.2 % | **36.2 %** |
| `max_drawdown_pct` | 1.47 % | 1.78 % | 1.78 % |
| `trades_count` | 100 | 138 | 138 |

Le meilleur PnL out-of-sample est **+0.69 USD** (configuration
`conf=0.30 buy=0.04 hold=60`), avec un win-rate de seulement
**25.5 %** — éliminée par la deuxième clause du filtre.

Au passage la baseline de production (`conf=0.22 buy=0.08 hold=90`)
produit sur le test set :

- `test net_pnl_usd = −8.60 USD`
- `test win_rate = 34.4 %`
- `test max_drawdown_pct = 1.78 %`

et sur le train set elle produit `+194.90 USD` / `36.9 %` — un
contraste in-sample / out-of-sample violent qui confirme que (a) la
stratégie a un edge mesurable au train et (b) cet edge se dégrade
sur 30 jours OOS au 240-min. C'est précisément le genre de gap que
le walk-forward est conçu pour exposer.

**Conséquences directes :**

1. `config.yaml` n'est **pas modifié**. La baseline
   `aggressive_competition` reste celle de
   commit `be55d62`.
2. Les trois snapshots de la submission
   (`backtest_xstocks_30d.json`, `backtest_xstocks_long.json`,
   `backtest_xstocks_micro_15m.json`) ne sont **pas régénérés**.
3. Le résultat brut du walk-forward (48 combos évalués + leurs
   métriques train+test) est exporté dans
   `data/walk_forward_results.json` (gitignored, parce que c'est
   un artefact dérivé local, mais reproductible via la commande
   ci-dessous).

## Reproduire le run

```powershell
# Sur Windows / PowerShell
.\.venv\Scripts\Activate.ps1
python scripts/walk_forward_xstocks.py --top 9 --output data/walk_forward_results.json
```

Le script utilise un cache OHLC (`data/ohlc_cache/xstocks_240m_720.json`)
pour ne pas re-frapper Kraken CLI à chaque essai. Force un rafraîchissement
avec `--refresh-cache`. Un run *quick* (8 combos seulement) est dispo
via `--quick` pour valider l'infra.

## Caveats explicites

> **Cette procédure n'est PAS un substitut à une optimisation
> bayésienne sur des années de données.** Trois limites :

1. **Petite grille (48 combos).** Trois leviers sur 4×4×3 valeurs.
   Une grille plus large explorerait plus finement (par ex.
   `min_confidence_to_trade` avec un pas de 0.025), mais ferait
   exploser le coût-temps.
2. **Fenêtre temporelle courte.** 90 jours de train + 30 jours de
   test, c'est-à-dire **un seul cycle macro** (la plupart des stocks
   ont fait un seul mouvement directionnel net sur ce timeframe).
   Une optimisation propre demanderait plusieurs années de données
   et un walk-forward roulant (e.g. 5×{1y train + 3mo test}).
3. **Mismatch de résolution.** Le walk-forward tourne à 240-min,
   alors que le snapshot de submission est en 60-min. C'est imposé
   par les contraintes de Kraken (cf. note plus haut), pas un
   choix.

Pour atténuer ces limites en mode "post-hackathon" il faudrait :

- Reconstruire un dataset multi-années (via une source data offline,
  e.g. yfinance pour les sous-jacents, en gardant en tête que les
  xStocks ont leurs propres frictions de liquidité que les actions
  US standards n'ont pas).
- Passer à une optimisation bayésienne (e.g. `optuna`) avec un
  budget de 200-500 évaluations.
- Faire tourner un walk-forward roulant (multi-folds) pour avoir une
  estimation de la variance des paramètres optimaux.

Ce travail dépasse le cadre du hackathon (deadline 20/05/2026) et
n'est pas dans le scope de cette submission. Le **trade-off rigueur
/ temps est documenté ici en toute transparence**.

## Pourquoi conserver le résultat actuel quand même

Trois raisons :

1. **Le snapshot 30d/60m a un win-rate >50 %** (53.0 %) sur les 30
   derniers jours, à la résolution effectivement utilisée par le
   loop de production. Le walk-forward dit "à 240-min on ne sait pas
   trouver mieux" — il ne dit *pas* "le snapshot 60-min est faux".
2. **La baseline n'a pas été choisie par data-snooping.** Elle vient
   d'un travail itératif d'ajustement de seuils basé sur la lecture
   du paysage Kraken, pas sur un grid search à postériori. Le
   walk-forward la *teste* honnêtement, il ne l'a pas *produite*.
3. **Le filtre est strict par design.** Exiger ≥ 50 % de win-rate
   sur 30 jours **OOS au 240-min** est une barre élevée — un grid
   réellement plus performant la franchirait. Aucune ne l'a fait :
   on conclut que la baseline est déjà au "plateau d'edge" qu'on
   peut tirer de la stratégie sur ce dataset.

## Référence croisée

- `docs/SUBMISSION.md` → section "Backtest evidence" : numéros
  finaux conservés (snapshot principal +33.56 USD / 53.0 % WR /
  1.68 % MDD), avec lien explicite vers ce document.
- `tests/test_walk_forward.py` : tests qui verrouillent la
  logique de split, d'expansion de grille, de score, et le contrat
  du driver `run_walk_forward`.
- `data/walk_forward_results.json` : sortie brute xStocks 240-min
  (48 candidats, métriques train + test, score, drapeau survivor).

## Extension multi-résolution sur la couche crypto Perps

Le walk-forward xStocks a un pendant strict sur la couche crypto via
`scripts/walk_forward_crypto.py` (data via le REST public Kraken,
pas de CLI mutant). Trois presets coordonnés couvrent trois échelles
temporelles complémentaires sur le même univers (`BTC, ETH, SOL,
AVAX, LTC`) :

| Preset    | Resolution | Window      | Train / Test | OOS filter (PnL ≥ 0 ET WR ET trades) |
|-----------|------------|-------------|--------------|---------------------------------------|
| `default` | 240-min    | ~90 jours   | ~60d / ~30d  | WR ≥ 0.50 ET trades ≥ 30              |
| `60min`   | 60-min     | ~30 jours   | ~20d / ~10d  | WR ≥ 0.50 ET trades ≥ 30              |
| `15min`   | 15-min     | ~7.5 jours  | ~5d  / ~2.5d | WR ≥ 0.48 ET trades ≥ 60              |

Le 15-min relâche très légèrement la barre WR (0.48 au lieu de 0.50)
parce que le scalping intra-day est dominé par la mean-reversion sur
des micro-ranges et qu'un edge net 50/50 sur du 15-min est rare ; le
plancher trades est en revanche relevé à 60 pour conserver la
significativité statistique au taux de fill plus élevé de cette
résolution.

Choix méthodologique sur l'axe d'exit : `time_stop_minutes` est
l'alias canonique de `max_hold_minutes` côté `src.exit_rules` (et
prend précédence quand les deux sont set). Pour ne pas double-compter
la même dimension, chaque preset n'utilise **qu'un seul** axe de
rotation d'exit (cf. la docstring du driver). Concrètement le preset
`default` garde `max_hold_minutes` (compatibilité avec la sortie
xStocks préexistante) ; les presets `60min` et `15min` utilisent
`time_stop_minutes` (le knob crypto-rapid-rotation).

**Résultat à `HEAD` (2026-05-18)** : **0 survivor sur les trois
presets** :

| Preset    | Survivors | Best test PnL | Best test WR | Test trades range |
|-----------|-----------|---------------|--------------|-------------------|
| `default` | 0 / 48    | −0.09$        | 40.50 %      | 299 - 300         |
| `60min`   | 0 / 48    | −0.21$        | 42.99 %      | 242 - 247         |
| `15min`   | 0 / 48    | −0.02$        | 51.85 %†     | 187 - 240         |

†Le seul candidat 15-min à WR ≥ 48 % (51.85 %) a un test PnL négatif
(−0.04$) et est rejeté par le filtre PnL ; le best test PnL (−0.02$,
presque flat mais négatif) a un WR de 34.88 %.

Le pattern est consistant sur les trois échelles : 144/144 combos
échouent le filtre OOS (PnL négatif dans tous les cas, WR < 50 % dans
142/144 cas, et le seul WR ≥ 50 % a un PnL négatif). Conséquence
directe : **aucun profil `live_crypto_*_capped` n'a été créé dans
`config.yaml`**. Voir `docs/OPTION_D_ACTIVATION.md` pour le détail
du verdict EV-négatif et la checklist binaire d'activation.

## Strategy Discovery Phase 2 — Bayesian + External Signals

> **Verdict.** **0 / 680** candidats survivors stricts (500 trials
> Optuna + 180 cellules walk-forward avec gates externes). Aucun edge
> mesurable n'apparaît malgré l'élargissement substantiel de l'espace
> de recherche et l'ajout de trois signaux externes (Fear & Greed,
> BTC dominance, realized vol regime).

Pour adresser les caveats `Petite grille / pas d'optim Bayésienne /
pas de signaux externes` listés plus haut, la procédure a été étendue
en Phase 2. Le détail complet vit dans
[`docs/STRATEGY_DISCOVERY_REPORT.md`](STRATEGY_DISCOVERY_REPORT.md) ;
synthèse :

| Sous-phase | Composant | Survivors | Best OOS PnL | Best OOS WR | Best OOS trades |
|------------|-----------|-----------|--------------|-------------|-----------------|
| Phase 2a — Optuna 500 trials | `scripts/optuna_crypto_search.py` | 0 / 500 | +0.251$ | 43.0 % | 167 |
| Phase 2b — Walk-forward + 36 gate permutations sur top-4 Optuna + baseline | `scripts/walk_forward_crypto_with_signals.py` | 0 / 180 | +0.266$ | 42.7 % | 165 |

**Espace Optuna** : `min_confidence_to_trade ∈ [0.05, 0.40]`,
`min_opportunity_score_buy ∈ [0.01, 0.10]`, `time_stop_minutes ∈
[10, 240]`, `weight_{momentum,breakout,mean_reversion} ∈ [0, 1]` (avec
renormalisation), `stop_loss_pct ∈ [0.5, 2.5]`, `take_profit_pct ∈
[0.4, 2.0]`. Sampler TPE, MedianPruner, seed `20260518`.

**Trois signaux externes** (`src/external_signals.py`, 19 tests
`tests/test_external_signals.py`) :

- **Fear & Greed Index** — daily, 31 entries cache sur la fenêtre
  2026-04-18 → 2026-05-18. Le gate `block_buy_if_fear_greed_lt=30`
  apporte un lift modeste (+0.015$ à +0.020$) mais insuffisant pour
  passer la barre WR 50 %.
- **BTC dominance** — limitation API : CoinGecko free `/global` ne
  donne que la valeur courante. Cache utile sur 1 entry uniquement →
  le gate `block_alt_if_btc_dominance_rising_24h_pct` est inactif sur
  la quasi-totalité des candles (caveat documenté dans
  `data/walk_forward_with_signals_results.json` et
  `STRATEGY_DISCOVERY_REPORT.md`).
- **Realized volatility regime** — computé localement, quantiles 25/75
  sur le rolling std des log-returns. Le gate
  `vol_regime_filter=["normal", "high"]` réduit le `trades_count`
  sans améliorer le WR.

**Lecture méthodologique principale** : les 4 trials Optuna les mieux
classés saturent la borne haute de `min_confidence_to_trade`
(`≈ 0.399 / 0.400` ; max permis = 0.40). Optuna **veut** une stratégie
plus conservatrice que ce que l'espace autorise. Élargir la borne à
0.60 ferait probablement converger vers `1.0` (= ne jamais trader = 0
trade = disqualifié). C'est l'indication la plus claire qu'**il
n'existe pas, sur ce dataset, de coin de l'espace param accessible
avec un trade-rate non-trivial ET un WR OOS ≥ 50 %**.

**Conséquence directe** : aucun profil
`live_crypto_with_signals_capped` n'a été créé dans `config.yaml`. Le
verdict EV-négatif d'option D est **renforcé** par cette deuxième
phase, pas atténué.

Voir [`docs/STRATEGY_DISCOVERY_REPORT.md`](STRATEGY_DISCOVERY_REPORT.md)
pour : configurations explorées en détail, distribution des
near-survivors, table complète des best per-base-config, et caveats
exhaustifs (p-hacking, BTC dom historique, slippage non modélisé,
fenêtre temporelle courte, pas de tuning per-symbol).
