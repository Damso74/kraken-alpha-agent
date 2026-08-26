# Pré-enregistrement H-KM-001 : rebond après déleveraging sur Kraken Futures

**Gelé le :** 2026-08-26, avant tout calcul de rendement historique de la stratégie

**Statut :** recherche read-only, aucun branchement paper ou live

**Branche :** `codex/kraken-microstructure-sprint`

## Question falsifiable

Après une baisse marquée du prix accompagnée d'une destruction d'open interest et
de flux de liquidation ou de vente agressive, le contrat perpétuel XBT de Kraken
présente-t-il un rebond positif sur les 12 heures suivantes, net de frais, de
slippage et d'un coussin de funding conservateurs ?

Le mécanisme attendu est un impact temporaire des ventes forcées. La direction
est fixée **long uniquement**. Un rendement négatif ne pourra pas être réinterprété
comme une preuve en faveur d'un signal short.

## Marché et sources

- Instrument primaire : `PF_XBTUSD`.
- Réplication secondaire, ouverte seulement après succès du test primaire :
  `PF_ETHUSD`.
- Fréquence : 1 heure.
- Prix : `GET https://futures.kraken.com/api/charts/v1/trade/{symbol}/1h`.
- Microstructure : `GET https://futures.kraken.com/api/charts/v1/analytics/{symbol}/{type}`
  avec `open-interest`, `liquidation-volume` et `aggressor-differential`.
- `slippage` et `funding` sont collectés comme diagnostics, mais ne servent pas à
  choisir les événements. Leur profondeur historique est plus courte.
- Aucune clé privée et aucune donnée issue du compte utilisateur.

Toutes les séries doivent être triées, dédupliquées et alignées exactement sur
l'heure UTC. Aucun forward-fill au-delà d'une barre n'est autorisé. Une barre
incomplète ou un trou dans l'une des entrées du signal invalide l'événement.

## Découpage chronologique scellé

| Segment | Fenêtre | Usage |
|---|---|---|
| Développement | 2023-06-01 au 2024-12-31 | contrôle de puissance et diagnostics uniquement |
| Validation | 2025-01-01 au 2025-12-31 | première décision de survie |
| Test final | 2026-01-01 au dernier jour UTC complet disponible | ouvert seulement si la validation passe |

Les 30 jours les plus récents sont intégralement dans le test final. Le programme
doit refuser de produire les métriques du test final si un manifeste de validation
ne confirme pas le passage de tous les gates.

## Signal fixé avant exécution

Pour chaque clôture horaire `t` :

1. `price_return_6h = close[t] / close[t-6] - 1` ;
2. `oi_change_6h = oi_close[t] / oi_close[t-6] - 1` ;
3. `liquidation_6h` = somme des volumes de liquidation de `t-5` à `t` ;
4. `sell_aggression_6h` = somme de l'aggressor differential de `t-5` à `t`,
   où une valeur positive désigne une domination des ventes agressives.

Les quantiles sont calculés causalement sur les **180 jours strictement antérieurs**
à `t`, avec la définition empirique *nearest rank*. Un événement exige :

- `price_return_6h` dans le décile inférieur ;
- au moins deux conditions parmi :
  - `oi_change_6h` dans le décile inférieur ;
  - `liquidation_6h` dans le décile supérieur ;
  - `sell_aggression_6h` dans le décile supérieur.

Une couverture d'au moins 95 % de la fenêtre causale est obligatoire. Après un
événement, aucun autre événement n'est accepté pendant 12 heures.

Ces seuils, la fenêtre de 180 jours et la règle « deux sur trois » ne seront pas
optimisés après observation des résultats.

## Exécution simulée et coûts

- Signal connu à la clôture de `t`.
- Entrée au prix d'ouverture de `t+1`.
- Sortie au prix d'ouverture de `t+13`, soit 12 heures de détention.
- Position longue, 1x, nominal fixe de 1 000 USD, une position maximum.
- Aucun stop, take-profit, réinvestissement ou séquençage intrabar.
- Coût primaire : **35 points de base aller-retour** :
  - 5 bps taker à l'entrée et 5 bps taker à la sortie ;
  - 10 bps de slippage adverse par côté ;
  - 5 bps de coussin de funding.
- Stress tests seulement, sans droit de repêchage : 20, 50 et 100 bps.

Le résultat primaire est celui à 35 bps. Un résultat positif uniquement à 20 bps
est rejeté comme trop dépendant de l'exécution.

## Baselines et inférence

- Baseline économique : mêmes entrées/sorties après simple décile inférieur du
  rendement prix 6 h, sans condition de microstructure.
- Placebo : pour chaque événement microstructure, tirage avec remise d'un événement
  de la baseline prix dans la même année et le même décile causal de volatilité
  24 h, avec 2 000 réplications.
- Bootstrap du rendement moyen par blocs calendaires de 7 jours, 10 000 réplications,
  graine fixe `20260826`.
- Une seule combinaison primaire est testée : XBT, horizon 12 h, coût 35 bps.
  Les stress tests ne peuvent pas produire un verdict positif autonome.

## Gates de passage

La validation puis le test final doivent chacun satisfaire **tous** les critères :

1. au moins 30 trades non chevauchants ;
2. PnL net cumulé strictement positif ;
3. rendement net moyen strictement positif ;
4. win rate supérieur ou égal à 50 % ;
5. borne basse de l'intervalle bootstrap unilatéral à 95 % du rendement moyen
   strictement positive ;
6. rendement moyen supérieur à la baseline prix appariée, avec p empirique
   inférieur ou égal à 0,05 ;
7. résultat encore positif au stress de 50 bps ;
8. jackknife conforme à G2 : retrait du trade de plus grande amplitude sans
   inversion du signe, baisse du rendement moyen supérieure à 50 %, ni hit-rate
   inférieur à 50 % ;
9. concentration acceptable : événement individuel au plus 20 % de la somme des
   contributions absolues, top 3 au plus 50 %, mois dominant au plus 40 % ;
10. au plus une rotation par jour et taux d'événements au plus 30 % des barres ;
11. aucune fuite temporelle, couverture ou anomalie de pagination non résolue.

Le statut `exploitable_candidate` est interdit tant que la validation et le test
final n'ont pas tous deux passé ces gates. La réplication ETH permet seulement de
qualifier la généralisation ; elle ne peut pas sauver un échec XBT.

## Règles d'arrêt

- Échec ou puissance insuffisante en validation : `not_supported` ou
  `insufficient_power`, test final maintenu scellé.
- Échec du test final : `not_supported`, sans modification de seuil ou inversion
  de direction.
- Toute nouvelle hypothèse exige un nouveau pré-enregistrement daté avant son run.
- Aucun ordre, aucune configuration live et aucune publication externe ne font
  partie de ce sprint.
