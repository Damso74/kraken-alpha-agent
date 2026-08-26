# Pré-enregistrement H-OF-001 — flux agressif hebdomadaire inter-places

Statut : **gelé avant tout calcul de performance historique** le 26 août 2026.

H-OF-001 est la troisième famille testée dans ce sprint, après H-KM-001 et
H-DV-001. Le seuil statistique tient compte des trois tentatives. Elle transpose
sur deux flux publics une publication qui agrège davantage de places : c'est
une réplication-proxy volontairement plus pauvre, pas le « world order flow »
exact des auteurs.

Les rendements 2024–2025 ont déjà été vus via d'autres signaux pendant ce
sprint. La validation ci-dessous est donc OOS pour **ce signal**, mais n'est pas
un holdout totalement aveugle au niveau du programme. Seul 2026 reste une
confirmation réellement scellée.

## Hypothèse et données

Le signe est fixé positif avant le test : un flux agressif acheteur agrégé sur
une semaine prédit un rendement BTC positif la semaine suivante.

- Binance Spot `BTCUSDT`, candles quotidiennes UTC. Pour chaque jour :
  `imbalance_B = (2 * taker_buy_quote_volume - quote_volume) / quote_volume`.
- Kraken Futures `PF_XBTUSD`, analytics CVD quotidiens UTC. Pour chaque jour :
  `imbalance_K = (buy_volume - sell_volume) / (buy_volume + sell_volume)`.
- Pour chaque semaine source complète du lundi 00:00 UTC au lundi suivant
  00:00 UTC, sommer d'abord les numérateurs et dénominateurs des sept jours sur
  chaque venue, puis définir
  `flow_week = (imbalance_B_week + imbalance_K_week) / 2`.
- Signal long si `flow_week > 0`, cash sinon. Aucun short, aucun levier supérieur
  à 1x, aucun seuil appris ou optimisé.

Une semaine avec un jour manquant, un volume nul/non fini ou des timestamps non
alignés est exclue, jamais imputée. Les champs `cvd` cumulatifs du serveur ne
sont pas utilisés ; seuls `buy_volume` et `sell_volume` du bucket le sont.

## Exécution et coûts gelés

- Décision : après la clôture des sept buckets quotidiens, le lundi à 00:00 UTC.
- Entrée : open Kraken `PF_XBTUSD` du lundi à 01:00 UTC.
- Sortie : open Kraken du lundi suivant à 01:00 UTC, exactement 168 heures.
- Les semaines consécutives peuvent se toucher à la même heure mais ne se
  chevauchent pas.
- Nominal fixe de 1 000 USD par semaine exposée, levier effectif 1x.
- Coût primaire all-in : 50 pb aller-retour = 10 pb de frais taker, 20 pb de
  slippage adverse et 20 pb de coussin de funding.
- Stress unique : 100 pb all-in.

## Découpage et embargo

- Données source à partir du 23 mars 2022.
- Développement : premières semaines complètes éligibles au 31 décembre 2023.
- Validation : semaines dont le signal et la sortie sont intégralement compris
  entre le 1er janvier 2024 et le 1er janvier 2026.
- Test final : semaines intégralement comprises en 2026 jusqu'à la dernière
  sortie complète disponible.

Le programme de validation ne télécharge ni ne lit aucune donnée de 2026. Le
test final reste verrouillé si une gate échoue ou si le pré-enregistrement ou
le harnais a changé.

## Comparateurs et inférence

Trois comparateurs sont gelés :

1. permutation des labels signal/cash à l'intérieur des strates année et décile
   causal de volatilité réalisée BTC sur 30 jours ;
2. même règle `> 0` avec le seul flux Binance ;
3. même règle `> 0` avec le seul flux Kraken.
4. momentum hebdomadaire naïf : long si le rendement Kraken de l'open du lundi
   00:00 à l'open du lundi suivant 00:00 de la semaine source est positif ;
5. exposition long toutes les semaines éligibles.

Les cinq stratégies discrètes supportent le même coût de 50 pb pour chaque
semaine exposée. Ce benchmark pénalise volontairement un roulement passif
hebdomadaire de la même manière que le signal ; il ne prétend pas représenter
un achat spot conservé sans roulement.

Le décile de volatilité compare la volatilité courante aux 52 observations
hebdomadaires strictement antérieures, avec au moins 95 % de couverture. La
permutation conserve exactement le nombre de semaines exposées dans chaque
strate et utilise 2 000 réplications avec la graine `20260826`. Le bootstrap
utilise des blocs de quatre semaines calendaires, 10 000 réplications et la
même graine.

La validation passe seulement si **toutes** les conditions suivantes sont
vraies :

1. au moins 30 semaines exposées ;
2. au moins 100 semaines OOS éligibles, exposition entre 20 % et 80 %, et au
   moins 12 changements d'état hebdomadaires ;
3. PnL net et rendement net moyen strictement positifs ;
4. win rate supérieur ou égal à 50 % et Sharpe hebdomadaire annualisé net
   supérieur ou égal à 0,5, semaines cash incluses avec rendement nul ;
5. borne basse unilatérale 95 % du bootstrap strictement positive ;
6. avantage sur placebo avec `p <= 0,0166667` (Bonferroni sur trois familles) ;
7. PnL encore positif à 100 pb all-in ;
8. PnL positif séparément en 2024 et en 2025 ;
9. PnL positif après retrait de chacun des huit trimestres ;
10. aucun trimestre ne représente plus de 50 % des gains positifs ;
11. rendement net moyen du proxy inter-places strictement supérieur à celui de
    chacun des deux signaux mono-venue ;
12. PnL total strictement supérieur à celui du momentum hebdomadaire et de
    l'exposition longue toutes les semaines ;
13. couverture et alignement de chaque source supérieurs ou égaux à 95 %.

Un succès de validation puis du test final signifie seulement
`candidate_for_forward_observation`. Il n'autorise ni paper trading, ni live,
ni ordre. Une modification de signe, agrégation, fenêtre, coût ou comparateur
constitue une nouvelle hypothèse et une nouvelle correction multiple.

## Sources figées

- Article primaire sur le flux mondial et les rendements crypto :
  <https://doi.org/10.1016/j.finmar.2026.101047>
- Binance Spot API, klines publiques :
  <https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md>
- Binance Market Data Only :
  <https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md>
- Kraken Futures Market Analytics :
  <https://docs.kraken.com/api/docs/futures-api/charts/market-analytics>
- Kraken Futures Candles :
  <https://docs.kraken.com/api/docs/futures-api/charts/candles>
- Frais Kraken Futures :
  <https://support.kraken.com/articles/360048917612-fee-schedule>
