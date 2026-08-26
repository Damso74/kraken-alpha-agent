# Pré-enregistrement H-QH-001 : order flow des quarts d'heure

**Gelé le :** 2026-08-26, avant tout calcul de rendement de validation

**Statut :** recherche read-only ; aucun ordre paper ou live

**Branche :** `codex/edge-sprint-qh-wof-exe`

## Question falsifiable

Sur Kraken Futures, une domination exceptionnelle des achats agressifs pendant
la première minute de `:00`, `:15`, `:30` ou `:45` prédit-elle un rendement
positif sur les huit heures suivantes, net de coûts, davantage que le même flux
observé sept minutes après ces bornes ?

La direction est fixée **long uniquement**. Une valeur positive de
`aggressor-differential` représente le volume taker buy moins le volume taker
sell selon la documentation Kraken. Le résultat ne pourra pas être inversé pour
fabriquer une stratégie short.

Cette étude est une réplication économique simplifiée, pas une réplication
exacte de Kim et Hansen (2026), qui étudient six perpetuals Binance et des
horizons de quatre à douze heures : <https://arxiv.org/abs/2607.09426>.

## Marché, source et calendrier scellé

- Primaire : `PF_XBTUSD`.
- Réplication obligatoire après succès primaire : `PF_ETHUSD`.
- Candles : Kraken Futures Charts `trade/{symbol}/1m`.
- Flux : Kraken Futures Charts
  `analytics/{symbol}/aggressor-differential?interval=60`.
- Aucune clé privée et aucune donnée de compte.

| Segment | Fenêtre | Usage |
|---|---|---|
| Warm-up | 2024-07-01 au 2024-12-31 | seuils causaux seulement |
| Validation | 2025-01-01 au 2025-12-31 | première décision |
| Test final | 2026-01-01 au dernier jour UTC complet | scellé |

Le programme doit refuser **avant chargement des données 2026** d'ouvrir le test
final si XBT validation et ETH réplication n'ont pas passé tous les gates avec
les mêmes hashes de pré-enregistrement et de code.

## Signal fixé

Pour chaque semaine UTC, le seuil est le quantile empirique nearest-rank 90 % de
`aggressor-differential` sur les 180 jours terminés strictement avant le lundi
00:00 UTC. Une couverture d'au moins 95 % des 259 200 minutes est obligatoire.
Le seuil est ensuite immuable pendant la semaine.

À chaque minute dont `minute % 15 == 0`, le signal apparaît seulement si :

1. la minute est complètement clôturée ;
2. le différentiel est strictement positif ;
3. il dépasse strictement le seuil causal ;
4. aucune position issue d'un signal précédent n'est encore ouverte.

Entrée à l'open de `T+1 minute`, sortie à l'open de `T+481 minutes`, soit huit
heures de détention. Long, levier économique 1x, nominal fixe de 1 000 USD, sans
stop, take-profit, réinvestissement ni donnée intrabar future.

## Placebo, coûts et inférence

Le placebo applique exactement le même seuil, la même règle et le même cooldown
aux minutes `minute % 15 == 7`. Pour chaque événement primaire, les rendements
placebo sont tirés avec remise dans le même mois UTC, 5 000 fois.

- Coût primaire : **20 bps aller-retour**, tout compris.
- Stress obligatoire : **40 bps aller-retour**.
- Bootstrap du rendement moyen par blocs calendaires journaliers : 10 000
  réplications, graine `20260826`.
- Seuil familial Bonferroni pour les trois familles du sprint :
  `0,05 / 3 = 0,016666...`.

Les frais ou hypothèses plus favorables ne peuvent pas sauver un échec.

## Gates cumulatifs

XBT validation, ETH réplication et XBT final doivent chacun satisfaire :

1. au moins 300 trades non chevauchants ;
2. PnL et rendement moyen nets strictement positifs ;
3. win rate au moins égal à 50 % ;
4. borne basse bootstrap unilatérale 95 % strictement positive ;
5. rendement supérieur au placebo apparié avec `p <= 0,016666...` ;
6. PnL encore positif à 40 bps ;
7. deux moitiés temporelles positives ;
8. PnL positif après retrait du meilleur mois ;
9. trimestre dominant au plus 40 % de la somme des contributions absolues et
   trade dominant au plus 10 % ;
10. couverture minute au moins 99 %, timestamps sur grille, aucune valeur
    invalide et seuil disponible pour chaque semaine ;
11. reproduction `--cache-only` byte-identique pour les métriques de décision.

Le qualificatif `exploitable_candidate` est interdit avant succès des trois
étapes. Même un succès ne constitue ni une autorisation paper/live, ni un conseil
financier.

## Règles d'arrêt

- Échec XBT : réplication et final restent scellés, hypothèse fermée.
- Échec ETH : final reste scellé, hypothèse fermée.
- Échec final : hypothèse fermée.
- Aucun changement de signe, horizon, phase, seuil ou coût après validation.
- Toute nouvelle variante exige un nouvel identifiant et des données futures
  jamais observées.
