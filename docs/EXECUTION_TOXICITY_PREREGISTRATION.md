# Pré-enregistrement H-EXE-001 : toxicité et résilience du carnet Kraken

**Gelé le :** 2026-08-26, avant toute observation forward formelle

**Statut :** collecte publique shadow uniquement, sans ordre paper ou live

**Branche :** `codex/edge-sprint-qh-wof-exe`

## Question falsifiable

Après un trade agressif suffisamment grand pour consommer au moins la quantité
affichée au meilleur prix opposé, une règle fixe combinant taille du sweep,
pression agressive sur cinq secondes et déséquilibre des cinq premiers niveaux
réduit-elle l'implementation shortfall d'au moins 5 points de base face à une
exécution taker immédiate, sans diminuer le taux de complétion sous 95 % ?

Le but est un avantage d'exécution, pas une prédiction autonome du rendement et
pas une autorisation de trading. La direction fictive de l'ordre est celle du
trade agressif déclencheur.

## Source et instruments

- Endpoint public : `wss://futures.kraken.com/ws/v1`.
- Feeds publics exclusivement : `book` et `trade`.
- Produits primaires : `PF_XBTUSD` et `PF_ETHUSD`.
- Aucun challenge, feed privé, identifiant ou secret.
- Aucune fonction d'ordre, de paper trading ou d'exécution n'est importée.

Le snapshot L2 complet initialise le carnet. Chaque delta doit avoir exactement
la séquence précédente plus un. Un delta avant snapshot, un trou, un retour de
séquence, un carnet croisé ou un côté vide invalide immédiatement la session.
Après reconnexion, seules de nouvelles séquences issues d'un snapshot frais sont
acceptées. Aucun trou n'est interpolé.

Chaque ligne conserve : timestamp exchange en millisecondes, horloge murale
locale en nanosecondes, horloge monotone locale, séquence, produit, type
d'événement et délai de transport observé. Les données brutes sont des JSONL
gzip append-only, rotés au changement de jour UTC ou à 256 Mio. Le plafond
initial est 100 Gio **partagé globalement** par les raw, observations, résumés,
journaux et digests de toutes les sessions sous l'output root. Il est recalculé
sur l'existant au début de chaque occurrence et partagé par les deux writers ;
un dépassement projeté provoque un arrêt fail-closed, jamais une suppression.

### Amendement opérationnel pré-validation du 26 août 2026

Avant le premier jour UTC complet, le canary long a révélé qu'une connexion TLS
pouvait rester ouverte sans aucun message public. Un watchdog fixe de 15
secondes a donc été ajouté : au-delà, la connexion est déclarée récupérable,
fermée et remplacée par un collecteur neuf exigeant de nouveaux snapshots. Les
données canary antérieures à cet amendement sont archivées et exclues de la
phase technique. Aucun seuil de signal, coût, probe ou gate économique n'a été
modifié.

## Phases forward

1. **Validation technique, 14 jours complets minimum** : disponibilité, pertes de
   séquence, dérive d'horloge, volumes, taille disque et exactitude des métriques.
   Ces données ne peuvent pas contribuer au verdict économique.
2. **Gel opérationnel** : hash du pré-enregistrement, du code, des constantes et
   du manifeste technique. Toute correction substantielle redémarre une nouvelle
   période technique.
3. **Validation scellée, 30 à 60 jours** : paramètres inchangés, fichiers
   append-only. Aucun verdict avant 30 jours complets, 10 000 observations
   terminées et deux produits exploitables.

La période commence uniquement au lancement effectif du collecteur. Aucun
historique reconstruit ne peut compléter le forward.

## Événement et variables fixes

Un événement est accepté lorsque la quantité d'un trade non-snapshot est au
moins égale à la quantité affichée au meilleur prix opposé. Le carnet utilisé
doit avoir un timestamp exchange **strictement antérieur** au trade et dater de
1 000 ms au maximum. Un carnet au même timestamp, postérieur ou plus ancien est
ignoré afin d'interdire une fuite par ordre d'arrivée entre feeds. Les événements
sont espacés d'au moins une seconde.

- `sweep_ratio = trade_qty / opposite_top_qty` ;
- `pressure_5s = signed_qty / total_qty`, alignée sur le côté du trade ;
- `imbalance_5 = (bid_depth_5 - ask_depth_5) / total_depth_5`, aligné sur le côté ;
- `toxicity_score = sweep_ratio + max(0, aligned_pressure) + max(0, aligned_imbalance)`.

La règle fictive traverse immédiatement le spread si le score est supérieur ou
égal à **2,0**. Sinon elle attend passivement au meilleur prix du même côté que
l'ordre fictif. Aucun seuil, horizon ou signe ne sera modifié après observation.

## Fills et coûts conservateurs

Baseline : taker immédiat au meilleur prix opposé au moment de la décision.

Route passive : la quote est considérée remplie seulement si les trades agressifs
opposés, au prix limite ou mieux, totalisent au moins **deux fois** toute la
quantité initialement affichée devant elle. La quantité du probe lui-même n'est
pas ajoutée au carnet et aucune priorité favorable n'est supposée.

À 60 secondes, toute quote non remplie est fictivement forcée taker au BBO alors
disponible avec une pénalité supplémentaire. Les coûts par jambe sont :

- taker : 5 bps de frais + 5 bps de slippage adverse ;
- maker rempli : 2 bps de frais ;
- non-complétion : coûts taker précédents + pénalité de 5 bps ;
- stress : 5 bps supplémentaires retranchés à chaque économie observée.

`implementation_shortfall = side_sign * (execution_price / decision_mid - 1)`
plus les coûts. L'économie est le shortfall de la baseline moins celui du routeur.

## Mesures

- markout signé adverse à 5, 30 et 60 secondes au premier book reçu après chaque
  horizon ;
- implementation shortfall baseline et routeur ;
- économie primaire et stressée en bps ;
- taux de complétion dans les 60 secondes ;
- taux de fills passifs pessimistes ;
- délai de transport observé p99 ;
- bootstrap unilatéral 95 % de l'économie moyenne par blocs de jours UTC, 10 000
  réplications, graine `20260826`.

## Gates cumulatifs

Le statut ne peut devenir `candidate_for_forward_observation` que si :

1. au moins 30 jours UTC scellés et 10 000 probes terminés ;
2. XBT et ETH ont chacun une économie moyenne strictement positive ;
3. économie moyenne agrégée au moins 5 bps ;
4. borne bootstrap journalière strictement positive ;
5. économie stressée moyenne au moins 5 bps ;
6. complétion dans l'horizon au moins 95 % ;
7. aucune session invalide, perte de séquence ou anomalie d'horloge non résolue ;
8. résultat stable dans les deux moitiés temporelles et sans dépendre d'un seul
   jour ou événement ;
9. reproduction locale à partir des fichiers bruts et hashes identique ;
10. tests et CI locale verts.

Même si tous les gates passent, la sortie est `REVIEW_REQUIRED`, jamais une
activation automatique. Un échec ferme H-EXE-001 sans changement post-hoc ; une
nouvelle règle exige un nouvel identifiant et une nouvelle collecte forward.

## Sécurité

Le collecteur est un observateur public borné. Il ne peut pas initialiser Kraken
paper, lire un compte, transférer des fonds, créer, modifier ou annuler un ordre.
Le passage à une observation paper ou live n'est pas couvert par ce document et
exigerait les gates globaux du dépôt ainsi qu'une autorisation humaine séparée.
