# Pré-enregistrement H-WOF-002 — world order flow cross-sectionnel

Statut : **gelé avant tout chargement d'une validation H-WOF-002** le 26 août
2026. Cette famille est distincte du proxy temporel BTC H-OF-001 déjà rejeté.

## Hypothèse

À univers connu causalement, les actifs du quintile supérieur de déséquilibre
hebdomadaire agrégé des klines Binance ont un rendement Kraken
positif la semaine suivante, net de coûts. Le signe est positif et ne sera pas
inversé après observation.

## Univers dynamique

- Spot Binance, quote `USDT`, statut `TRADING`, une paire maximum par actif.
- Actif également négociable long-only sur Kraken au timestamp de décision.
- L'univers Kraken forward provient de l'endpoint public officiel `AssetPairs`
  avec `assetVersion=1` : Spot currency, lot unitaire, statut online, quotes
  USD/USDT/USDC par priorité, hors fiat/stablecoins/xStocks. Au-delà de 80
  actifs, le cap lexical déterministe est appliqué avant l'intersection Binance.
- Minimum 30 actifs possédant une semaine complète de flux et deux prix Kraken.
- Le snapshot d'univers utilisé doit avoir été observé au plus tard au début de
  la semaine source. Un snapshot futur ou l'univers courant rétro-projeté est
  interdit.
- Si un membre causal manque de flux ou de prix, la semaine entière est exclue,
  sans imputation ni remplacement par l'actif suivant.

L'audit de faisabilité `docs/WORLD_ORDER_FLOW_FEASIBILITY.md` fait partie du
pré-enregistrement. En l'absence de snapshots historiques officiels complets,
la validation historique reste verrouillée et la collecte est forward-only.

## Signal, décision et portefeuille

Pour l'actif `i` et la semaine UTC du lundi au lundi :

`flow_i = (2 * taker_buy_quote_volume_i - quote_volume_i) / quote_volume_i`

Les deux volumes proviennent des champs agrégés de klines Spot 1d. Il s'agit
d'un proxy Binance, pas d'une réplication tick-exacte du world order flow
multi-places de l'article. Un audit d'équivalence `aggTrades` borné à BTCUSDT et
ETHUSDT le **15 juin 2023 UTC** vérifie l'erreur et l'accord de signe quotidien
sans modifier le signal primaire. Les deux ZIP quotidiens et leurs SHA-256 sont
figés dans le manifeste d'audit avant calcul.

- décision après clôture complète de la semaine source ;
- classement décroissant, égalités départagées par ticker ;
- sélection des `ceil(N / 5)` premiers, uniquement si leur score est strictement
  positif ; les slots non positifs restent cash ;
- chaque slot du quintile cible reçoit `1 / ceil(N / 5)` du nominal ; un slot
  non positif reste cash et son poids n'est pas redistribué ;
- entrée au premier prix Kraken causal disponible une heure après la décision ;
- sortie exactement sept jours plus tard ;
- aucune position short, aucun levier supérieur à 1x ;
- si aucun score sélectionné n'est positif, portefeuille intégralement cash.

## Fenêtres gelées

- Réplication descriptive de l'article : jusqu'au 30 juin 2022, jamais utilisée
  pour conclure sur H-WOF-002.
- Développement : 1er juillet 2022 au 31 décembre 2023.
- Validation : positions dont la décision, l'entrée et la sortie sont toutes
  comprises entre le 1er janvier 2024 inclus et le 1er janvier 2026 exclu, sous
  réserve de provenance causale de l'univers.
- Final scellé : décisions à partir du 1er janvier 2026.
- Forward propre : snapshots collectés après le 26 août 2026, avec au moins 30
  semaines indépendantes avant décision.

Le final n'est déverrouillé que par une validation ayant passé toutes les gates
avec le SHA-256 identique de ce fichier et des sources du harnais.

## Coûts et inférence

- coût primaire : 100 pb aller-retour par semaine exposée ;
- stress : 150 pb ;
- nominal et pondération fixes ; cash = rendement nul et aucun frais ;
- bootstrap par blocs de quatre semaines, 10 000 réplications, seed `20260826` ;
- permutation de signe, 2 000 réplications, même seed ;
- seuil Bonferroni : `p <= 0.0166667` pour trois nouvelles familles.

## Gates cumulatives

1. univers point-in-time causal et provenance hashée ;
2. couverture intégrale de chaque semaine incluse ;
3. au moins 100 semaines éligibles et 30 semaines exposées ;
4. rendement moyen net positif à 100 et 150 pb ;
5. borne basse unilatérale 95 % du bootstrap strictement positive ;
6. permutation `p <= 0.0166667` ;
7. au moins deux années positives séparément ;
8. aucun trimestre ne fournit plus de 40 % des gains trimestriels positifs ;
9. résultat toujours positif après retrait de chaque trimestre ;
10. reproduction `--cache-only` byte-for-byte sur les métriques ;
11. tests et périmètre Ruff CI verts.

Un passage signifie uniquement `candidate_for_forward_observation`. Il
n'autorise aucun ordre, paper trading ou live. Tout changement de signe,
univers, rang, coût, horizon ou filtre constitue une nouvelle hypothèse.
