# Strategy discovery report — Phase 2 (Bayesian + external signals)

> **Verdict.** Aucun edge mesurable n'a survécu au filtre OOS strict. La
> Phase 2 — optimisation Bayésienne (500 essais Optuna) sur grille élargie
> + intégration de trois signaux externes (Fear & Greed Index, BTC
> dominance, realized volatility regime) — confirme statistiquement le
> verdict EV-négatif déjà documenté en Phase 1 (walk-forward déterministe
> 240/60/15 min). **Aucun profil `live_crypto_with_signals_capped` n'a été
> créé** dans `config.yaml` ; option D reste DÉCONSEILLÉE.
>
> Ce document conserve la procédure complète à des fins (a) d'auditabilité
> jury, (b) de rigueur méthodologique anti-curve-fit, et (c) de
> réutilisation future si une autre asset class ou une autre fenêtre
> temporelle change la donne.

## TL;DR (1 paragraphe)

Sur 500 essais Optuna (TPE + MedianPruner, espace continu vs grille
discrète) puis 180 cellules walk-forward avec gates de signaux externes,
**0/680 candidats** passent simultanément `test_pnl_usd ≥ 0.20$`,
`test_win_rate ≥ 50 %` et `test_trades_count ≥ 30`. Les 4 meilleurs
near-survivors (Optuna trials 99/303/369/185, plus le baseline avec gate
F&G\_lt=30) atteignent au mieux **+0.27$ OOS / WR 42-44 % / 165-167
trades** — la barre PnL et trade count est franchie, **la barre
win-rate ne l'est pas**. Le fait que les paramètres optimaux
(`min_confidence_to_trade ≈ 0.40`, top de la borne supérieure de
l'espace de recherche, et `min_opportunity_score_buy ≈ 0.10`, idem)
saturent les bornes hautes de l'espace est lui-même un signal : la
stratégie veut être **plus conservatrice** que la grille testée
n'autorise, ce qui n'est pas un edge — c'est une indication que sur ce
dataset la stratégie devrait simplement trader moins, pas mieux.

## Méthodologie

### Phase 1 — Optuna 500 trials (Bayesian optimization)

| Composant | Fichier |
|-----------|---------|
| Driver | [`scripts/optuna_crypto_search.py`](../scripts/optuna_crypto_search.py) |
| Sortie brute | `data/optuna_crypto_results.json` (gitignored, ~19 MB) |
| Logique walk-forward | [`src/walk_forward.py`](../src/walk_forward.py) |
| Sampler | TPE (Tree-structured Parzen Estimator) — Optuna default |
| Pruner | `MedianPruner(n_startup_trials=10)` |
| Seed | `20260518` (reproducible) |
| n_trials | 500 |
| Universe | BTC, ETH, SOL, AVAX, LTC (5 paires Perps) |
| Resolution | 60 min × 720 candles (~30 jours) |
| Train/test split | `train_fraction=2/3` ⇒ ~20j train / ~10j test |
| Profile | `micro_live_100eur_crypto` (engine: futures, leverage 1.0) |
| Objective | `test_pnl_usd / max(test_mdd_pct, 0.5)` (à maximiser) |
| Filtre OOS strict | `test_pnl_usd ≥ 0.20$` ET `test_win_rate ≥ 0.50` ET `test_trades_count ≥ 30` |
| Elapsed | 918.7 s (≈ 15 min) |

**Espace de recherche élargi vs la grille déterministe précédente** :

| Paramètre | Phase 1 espace | Avant (grille discrète) |
|-----------|----------------|-------------------------|
| `min_confidence_to_trade` | continu `[0.05, 0.40]` | `{0.10, 0.15, 0.22, 0.30}` |
| `min_opportunity_score_buy` | continu `[0.01, 0.10]` | `{0.04, 0.06, 0.08, 0.10}` |
| `time_stop_minutes` | entier `[10, 240]` | `{60, 90, 180}` |
| `weight_momentum` | continu `[0.0, 1.0]` | non explorée |
| `weight_breakout` | continu `[0.0, 1.0]` | non explorée |
| `weight_mean_reversion` | continu `[0.0, 1.0]` | non explorée |
| `stop_loss_pct` | continu `[0.5, 2.5]` | non explorée |
| `take_profit_pct` | continu `[0.4, 2.0]` | non explorée |

Les trois poids ensemble sont renormalisés dans `_build_settings_override`
(`src/backtest.py`) pour conserver une contribution directionnelle fixe
de 0.85 (les poids auxiliaires liquidity / volatility / spread penalty
gardent leur impact original).

> **Note méthodologique.** `max_funding_rate_pct_per_hour` n'a pas été
> ajouté à l'espace Optuna parce que le backtester n'inclut pas la
> mécanique d'accrual du funding — l'inclure aurait introduit du bruit
> sans signal. Cette limite est explicite dans
> [`docs/METHODOLOGY.md`](METHODOLOGY.md).

### Phase 2 — Trois signaux externes

| Signal | Source | Granularité | Cache | Tests |
|--------|--------|-------------|-------|-------|
| Fear & Greed Index | `https://api.alternative.me/fng/?limit=365` | quotidien (0-100) | `data/external_cache/fear_greed.json` | 5 |
| BTC dominance | `https://api.coingecko.com/api/v3/global` | **current uniquement** | `data/external_cache/btc_dominance.json` | 6 |
| Realized vol regime | computé localement depuis OHLC, rolling std des log-returns × √annualisation, quantiles 25/75 | par-candle | (pas de cache) | 5 |

**Limitation majeure — BTC dominance.** L'endpoint gratuit `/global` de
CoinGecko ne donne que la valeur courante du jour. Aucun endpoint public
gratuit ne fournit l'historique journalier de la dominance (le payant
`/coins/markets` snapshote bien chaque coin, mais reconstruire la
dominance demande une requête + agrégation par jour, ce qui sort du
budget du hackathon). En pratique : pendant le run Phase 3 du
2026-05-18, la dominance n'est connue que pour la date courante (1
entry dans le cache) ⇒ **le gate
`block_alt_if_btc_dominance_rising_24h_pct` n'est évaluable que sur les
candles dont la date est couverte par le cache** ; pour tous les autres
candles, le gate ne déclenche jamais. Ce caveat est documenté en clair
dans `data/walk_forward_with_signals_results.json`
(`external_signal_diagnostics.btc_dominance_caveat`) et conservé tel
quel — masquer ce point créerait l'illusion d'un edge non-mesuré.

**Tests** (`tests/test_external_signals.py`, 19 tests) couvrent : parsing
HTTP, cache hit/miss, classification volatility low/normal/high, et
intégration avec `apply_actionability_gates`.

### Phase 3 — Walk-forward final avec gates externes

| Composant | Fichier |
|-----------|---------|
| Driver | [`scripts/walk_forward_crypto_with_signals.py`](../scripts/walk_forward_crypto_with_signals.py) |
| Sortie brute | `data/walk_forward_with_signals_results.json` (gitignored) |
| Universe | identique Phase 1 (5 paires) |
| Resolution | 60 min × 720 candles |
| Train/test split | `train_fraction=2/3` ⇒ ~20j train / ~10j test |
| Filtre OOS strict | identique Phase 1 |
| Cellules évaluées | 5 base configs × 36 permutations gates = **180 cellules** |
| Elapsed | 391.6 s (≈ 6.5 min) |

**Cinq base configs** sélectionnées :

1. `baseline_active_profile` (= `micro_live_100eur_crypto` brut, sans override)
2. `optuna_top1_trial99` (best Optuna trial)
3. `optuna_top2_trial303`
4. `optuna_top3_trial369`
5. `optuna_top4_trial185`

Les 4 trials Optuna ne sont pas des survivors stricts (cf. Phase 1), mais
ce sont les 4 trials distincts (paramètres ≠) avec **objective score le
plus élevé** ET **test PnL ≥ 0.20$** ET **trades ≥ 30**. Ils échouent
uniquement sur la barre WR ≥ 50 % (ils plafonnent à WR ≈ 41-43 %). Les
inclure en Phase 3 teste l'hypothèse : *est-ce que les gates externes
peuvent suffire à pousser leur win-rate au-dessus de 50 % ?*

**36 permutations de gates** (`GATE_LADDERS` dans le driver) :

| Gate | Échelle |
|------|---------|
| `block_buy_if_fear_greed_lt` | `{None, 25, 30}` (block extrême peur) |
| `block_buy_if_fear_greed_gt` | `{None, 70, 75}` (block extrême greed) |
| `block_alt_if_btc_dominance_rising_24h_pct` | `{None, 1.0}` (block alts si BTC dom +1%/24h) |
| `vol_regime_filter` | `{[], ["normal", "high"]}` (block si regime=low) |

Total = 3 × 3 × 2 × 2 = **36 permutations**, soit 5 × 36 = **180
cellules** dans le cap de 200 imposé par le brief.

## Résultats

### Phase 1 — Optuna 500 trials

```
n_trials_completed = 500
survivors_count    = 0  (filtre OOS strict)
best_value         = 0.5016 (objective)
elapsed_seconds    = 918.7
```

**Distribution observée** (extraite de `data/optuna_crypto_results.json`,
`top_k_failed_for_reference`) :

| Trial | min_conf | min_opp | time_stop | wm | wb | wmr | sl | tp | OOS PnL | OOS WR | OOS trades |
|-------|----------|---------|-----------|-----|-----|------|------|------|---------|--------|------------|
| 99    | 0.399    | 0.0998  | 91 min    | 0.72| 0.97| 0.067| 1.48| 0.82| +0.251$ | 41.6 % | 169        |
| 303   | 0.400    | 0.0861  | 70 min    | 0.55| 0.90| 0.174| 1.15| 0.86| +0.251$ | 41.6 % | 169        |
| 369   | 0.400    | 0.0853  | 91 min    | 0.93| 0.94| 0.061| 1.45| 0.89| +0.251$ | 41.6 % | 169        |
| 185   | 0.400    | 0.0934  | 91 min    | 0.84| 0.99| 0.083| 1.43| 0.81| +0.249$ | 43.0 % | 167        |

**Observation forte sur les bornes** : `min_confidence_to_trade` sature
à `≈ 0.40` (max de l'espace `[0.05, 0.40]`) sur le top-4. C'est le
signal classique d'un espace de recherche trop étroit côté
conservatisme : Optuna **veut** une stratégie qui filtre encore plus
durement les BUY. Cela ne signifie pas qu'il existe un coin gagnant
au-delà — élargir à `[0.05, 0.60]` ferait probablement converger
toutes les solutions vers `1.0` (= ne jamais trader = `trades_count = 0`
= disqualifié par la troisième barre du filtre).

Verdict Phase 1 : **0/500 essais survivors stricts.** Aucun edge
significatif identifié dans l'espace param élargi.

### Phase 2 — Caractérisation des signaux externes

| Signal | Entries cache (run 2026-05-18) | Couverture | Comportement |
|--------|---------------------------------|------------|--------------|
| Fear & Greed | 31 jours | 2026-04-18 → 2026-05-18 | Couvre intégralement la fenêtre OOS |
| BTC dominance | 1 jour | 2026-05-18 uniquement | Caveat ci-dessus — gate inactif sur la quasi-totalité des candles |
| Realized vol regime | n/a (computé per-candle) | 100 % des candles | Distribution observée : `low` ≈ 25 %, `normal` ≈ 50 %, `high` ≈ 25 % par construction quantile |

19 tests `tests/test_external_signals.py` valident le parsing, le
caching, la classification, et l'intégration dans
`apply_actionability_gates`.

### Phase 3 — Walk-forward avec gates externes

```
cells_total       = 180
cells_evaluated   = 180
strict_survivors  = 0
elapsed_seconds   = 391.6
```

**Top 5 cellules par PnL OOS** (toutes échouent le filtre WR ≥ 50 %) :

| Base | F&G_lt | F&G_gt | BTC dom | Vol | OOS PnL | OOS WR | OOS MDD | OOS trades |
|------|--------|--------|---------|-----|---------|--------|---------|------------|
| optuna_top1_trial99  | 30 | None | None | [] | **+0.266$** | 42.7 % | 0.37 % | 165 |
| optuna_top1_trial99  | 30 | None | 1.0  | [] | +0.266$    | 42.7 % | 0.37 % | 165 |
| optuna_top1_trial99  | 30 | 70   | None | [] | +0.266$    | 42.7 % | 0.37 % | 165 |
| optuna_top2_trial303 | 30 | None | None | [] | +0.266$    | 42.7 % | 0.37 % | 165 |
| optuna_top4_trial185 | 30 | None | None | [] | +0.251$    | 44.2 % | -      | 163 |

**Best cellule par base config** :

| Base | OOS PnL | OOS WR | OOS trades | Gates qui aident |
|------|---------|--------|------------|------------------|
| baseline_active_profile | -0.246$ | 37.2 % | 222 | F&G_lt=30 + vol regime [normal, high] |
| optuna_top1_trial99 | +0.266$ | 42.7 % | 165 | **F&G_lt=30** (lift +0.015$ vs sans gate) |
| optuna_top2_trial303 | +0.266$ | 42.7 % | 165 | F&G_lt=30 |
| optuna_top3_trial369 | +0.266$ | 42.7 % | 165 | F&G_lt=30 |
| optuna_top4_trial185 | +0.251$ | 44.2 % | 163 | F&G_lt=30 |

**Lecture des résultats** :

1. Le gate `block_buy_if_fear_greed_lt=30` apporte un lift mesurable
   mais **modeste** (+0.015$ à +0.020$ OOS PnL sur le top-4) qui ne
   suffit pas à franchir la barre WR 50 %.
2. Le gate `block_buy_if_fear_greed_gt` (block extrême greed) n'a
   **aucun impact** : les 30 derniers jours du dataset n'ont jamais
   touché la zone Greed extrême (F&G > 70-75) sur la fenêtre 2026-04-18
   → 2026-05-18.
3. Le gate `block_alt_if_btc_dominance_rising_24h_pct=1.0` n'a
   **aucun effet observable** parce que (a) le cache historique BTC
   dominance ne contient qu'une seule entrée et (b) sur 1 entry il est
   impossible de calculer une variation 24h.
4. Le `vol_regime_filter=["normal", "high"]` (= block les BUY pendant
   les régimes de basse volatilité) **dégrade** légèrement le PnL sur
   les configs Optuna (de +0.266$ à -0.005$ → -0.030$) parce qu'il
   réduit le `trades_count` sous le seuil critique. Sur le baseline il
   apporte un léger lift mais reste largement négatif.
5. **Aucune combinaison** de gates ne pousse simultanément PnL ≥ 0.20$,
   WR ≥ 50 % et trades ≥ 30.

Verdict Phase 3 : **0/180 cellules survivors stricts.**

## Verdict EV final

**Le fait de ne PAS avoir d'edge mesurable sur 680 candidats (500 Optuna
+ 180 walk-forward gates) est lui-même un résultat fort.**

| Variante option D | Survivors | Best OOS PnL | Best OOS WR | EV expected | Recommandation |
|-------------------|-----------|---------------|-------------|-------------|----------------|
| Walk-forward 240-min déterministe | 0 / 48  | -0.09$  | 40.50 % | -2 à -5$ / 24h | **DÉCONSEILLÉ** |
| Walk-forward 60-min déterministe  | 0 / 48  | -0.21$  | 42.99 % | -2 à -5$ / 24h | **DÉCONSEILLÉ** |
| Walk-forward 15-min déterministe  | 0 / 48  | -0.02$  | 51.85 %† | -2 à -5$ / 24h | **DÉCONSEILLÉ** |
| Optuna 500 trials Bayesian        | 0 / 500 | +0.251$ | 43.0 %  | indéterminée  | **DÉCONSEILLÉ** |
| Walk-forward + signaux externes   | 0 / 180 | +0.266$ | 42.7 %  | indéterminée  | **DÉCONSEILLÉ** |

†Voir `docs/OPTION_D_ACTIVATION.md` : le best WR 15-min a un PnL négatif.

**Aucun profil `live_crypto_with_signals_capped` n'a été créé** dans
`config.yaml`. Le profil `micro_live_100eur_crypto` reste tel quel et
n'est jamais le profil actif par défaut.

## Caveats méthodologiques explicites

1. **p-hacking risk avec 680 configs.** Tester 500 trials Optuna +
   180 cellules walk-forward augmente *mécaniquement* la probabilité de
   trouver un faux positif par hasard. C'est précisément pour cela que
   le filtre OOS strict (PnL ≥ 0.20$ ET WR ≥ 50 % ET trades ≥ 30) est
   conservé — il rejette les "gagnants chanceux d'une fenêtre" tout en
   restant atteignable par une stratégie qui aurait un edge réel.
   Aucune correction de Bonferroni n'est appliquée parce qu'on ne
   recherche pas la significativité statistique d'un *single trial* ;
   on cherche un *winner stable* qui passerait n'importe quel filtre
   raisonnable (et même celui-là est un seuil minimal).
2. **Saturation des bornes Optuna**
   (`min_confidence_to_trade` colle à 0.40) suggère qu'un edge
   "trade-less" pourrait exister, mais en pratique il ferait
   `trades_count → 0` ⇒ disqualifié par la troisième barre. C'est une
   indication forte qu'**il n'existe pas de coin de l'espace param
   accessible avec une fréquence de trade non-triviale et un WR ≥ 50 %**.
3. **BTC dominance historique manquante** (cf. caveat ci-dessus). Si
   un jour un cache historique dense est disponible (e.g. snapshots
   quotidiens accumulés sur 6 mois), la phase 3 devrait être ré-exécutée
   pour valider que le gate BTC dom n'est effectivement pas un signal —
   le résultat actuel est *conservateur* sur ce gate (= "on ne peut pas
   conclure qu'il aide" plutôt que "il n'aide pas").
4. **Backtest vs live** :
   - Slippage non modélisé (au-delà des frais taker)
   - Latence ordre-fill non modélisée (à 60-min ce serait négligeable
     en théorie, mais Kraken Futures peut avoir des spreads plus larges
     pendant les heures off-peak)
   - Funding accrual non modélisé (cf. note Phase 1)
   - Aucune simulation des conditions de marché que les 30 derniers
     jours n'ont pas vues (e.g. flash crash, panic buying, halt)
5. **Fenêtre temporelle courte.** 30 jours de données = 1 cycle macro
   au mieux. Une recherche réellement robuste demanderait 6-12 mois
   d'historique et un walk-forward roulant multi-folds. Le hackathon
   contraint cette analyse à la fenêtre disponible via le REST public
   Kraken.
6. **Cinq paires uniquement.** L'univers crypto Kraken Perps est
   beaucoup plus large ; tester sur top-5 par liquidité est raisonnable
   pour le hackathon mais n'épuise pas l'espace de marché.
7. **Pas de tuning per-symbol.** Toute la procédure utilise les *mêmes*
   paramètres pour les 5 paires. Un edge per-symbol pourrait exister
   (e.g. AVAX se comporte différemment de BTC) mais nécessiterait 5×
   plus d'essais Optuna et un risque de p-hacking proportionnel.

## Référence croisée

- `docs/METHODOLOGY.md` — section "Strategy Discovery Phase 2 — Bayesian
  + External Signals" (résumé synthétique de ce report)
- `docs/SUBMISSION.md` — section "Strategy Exploration Attempts"
  (chronologie complète des 5 phases)
- `docs/OPTION_D_ACTIVATION.md` — verdict EV-négatif sur les 5
  variantes
- `scripts/optuna_crypto_search.py` — driver Optuna
- `scripts/walk_forward_crypto_with_signals.py` — driver Phase 3
- `src/external_signals.py` — fetch + classification des trois signaux
- `tests/test_external_signals.py` — 19 tests
- `data/optuna_crypto_results.json` — sortie Optuna (gitignored)
- `data/walk_forward_with_signals_results.json` — sortie Phase 3
  (gitignored)
- `data/walk_forward_crypto_*.json` — sorties Phase 1 déterministe
  (gitignored)
- `AGENTS.md` — anti-curve-fit policy + override "futures + leverage"
