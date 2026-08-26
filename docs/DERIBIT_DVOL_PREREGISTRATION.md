# Pré-enregistrement H-DV-001 — proxy DVOL de compensation du risque

Statut : **gelé avant tout calcul de performance historique** le 26 août 2026.

H-DV-001 est la deuxième famille testée dans ce sprint, après le rejet de
H-KM-001. Le seuil statistique tient donc compte de deux tentatives. Cette étude
est exploratoire : le DVOL public n'est pas le facteur VoV option-implied
reconstruit depuis toute la surface d'options dans Atanasova et al. Le papier
primaire accessible indique une prédictivité, mais ne publie pas le signe du
coefficient. Le signe positif ci-dessous est une inférence ex ante de
compensation du risque, pas une réplication annoncée.

## Hypothèse et données

- Actif d'expression : `PF_XBTUSD`, long-only, levier effectif 1x.
- Signal externe : candles quotidiennes BTC DVOL de Deribit via
  `public/get_volatility_index_data`, résolution `1D`.
- Prix d'exécution : candles horaires Kraken Futures Charts `PF_XBTUSD`.
- Aucune donnée manquante n'est imputée ou forward-fillée.
- Une candle DVOL horodatée au jour `t` n'est réputée connue qu'à sa clôture,
  `t+1 00:00 UTC`.

Pour chaque jour complet `t` :

1. calculer les sept variations `log(DVOL_close_d / DVOL_close_d-1)` à partir
   de huit closes consécutifs ;
2. définir `VoV7_t` comme leur écart-type échantillon ;
3. calculer `q90_t` par nearest-rank sur les 365 valeurs `VoV7` strictement
   antérieures ;
4. déclencher un signal si `VoV7_t >= q90_t` et qu'aucune position issue de
   H-DV-001 n'est encore ouverte.

Il faut 365 observations historiques et au moins 95 % de couverture avant de
former le premier seuil. Le signal est **long**. Il n'existe qu'une fenêtre,
un seuil et une direction ; aucun choix après observation des résultats.

## Exécution et coûts gelés

- Entrée : open Kraken à `t+1 01:00 UTC`, soit une heure après la clôture DVOL.
- Sortie : open Kraken exactement 168 heures après l'entrée.
- Positions non chevauchantes ; nominal fixe de 1 000 USD par trade.
- Coût primaire all-in : 50 points de base aller-retour, composé de 10 pb de
  frais taker, 20 pb de slippage adverse et 20 pb de coussin de funding.
- Stress unique : 100 pb all-in.

Le coussin fixe évite de sous-estimer le funding sans introduire une autre
série ou une règle estimée après coup. Une éventuelle observation forward
devrait comptabiliser le funding réellement payé en plus de ce test.

## Découpage immuable

- Warm-up : à partir du premier DVOL officiel disponible, le 24 mars 2021.
- Développement : premières observations éligibles au 31 décembre 2023 inclus.
- Validation : du 1er janvier 2024 au 31 décembre 2025 inclus.
- Test final : du 1er janvier 2026 à la dernière journée complète disponible.

Chaque segment applique un embargo de sortie : un événement est exclu si sa
sortie à 168 heures franchit la borne de fin du segment. La validation ne lit
donc aucun prix de 2026 pour terminer un trade commencé fin décembre 2025.

Le programme de validation ne télécharge ni ne lit aucune donnée de 2026. Le
test final reste verrouillé si une seule gate de validation échoue ou si le
pré-enregistrement ou le harnais a changé.

## Inférence et gates obligatoires

Le comparateur est un placebo apparié sur l'année civile et le décile causal de
volatilité réalisée BTC sur 30 jours. Chaque réplication tire le même nombre de
dates éligibles, sans chevauchement, parmi les jours non-signal. Le test utilise
2 000 réplications et la graine `20260826`. Le bootstrap utilise des blocs
calendaires de quatre semaines, 10 000 réplications et la même graine.

La validation passe seulement si **toutes** les conditions suivantes sont
vraies :

1. au moins 30 trades indépendants ;
2. PnL net total strictement positif ;
3. rendement net moyen strictement positif ;
4. win rate supérieur ou égal à 50 % ;
5. borne basse unilatérale 95 % du bootstrap strictement positive ;
6. avantage sur le placebo apparié avec `p <= 0,025` (Bonferroni H-KM-001 et
   H-DV-001) ;
7. PnL encore positif à 100 pb all-in ;
8. PnL positif séparément en 2024 et 2025 ;
9. PnL positif après retrait de chacun des huit trimestres de validation ;
10. aucun trimestre ne représente plus de 50 % de la somme des gains positifs ;
11. couverture et alignement des données supérieurs ou égaux à 95 %.

Un succès de validation puis du test final signifie uniquement
`candidate_for_forward_observation`. Il n'autorise ni paper trading, ni live,
ni ordre. Toute modification de fenêtre, seuil, direction ou coût crée une
nouvelle hypothèse et une nouvelle correction pour tests multiples.

## Sources figées

- API Deribit :
  <https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data>
- Méthodologie DVOL :
  <https://insights.deribit.com/exchange-updates/dvol-deribit-implied-volatility-index/>
- Prépublication à l'origine de la piste VoV :
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6771170>
- Candles Kraken Futures :
  <https://docs.kraken.com/api/docs/futures-api/charts/candles>
- Frais Kraken Futures :
  <https://support.kraken.com/articles/360048917612-fee-schedule>
