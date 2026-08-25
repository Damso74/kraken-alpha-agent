# Alpha Reality Check - sprint fondateur de 14 jours

**Date de départ :** 2026-08-25

**Objectif :** obtenir une première mission payée, puis trois audits avant tout développement SaaS

**Positionnement :** audit indépendant de backtests, sans promesse de rendement ni conseil d'investissement

## Décision stratégique

La stratégie au meilleur rapport délai, risque et probabilité d'encaissement est une vente de service menée par le fondateur. Le dépôt ne contient aucun signal de trading validé à exploiter. Il contient en revanche une preuve rare et vérifiable : un pipeline positif a été démonté, réparé, rejoué puis arrêté lorsque l'effet a disparu.

Le produit vendu est donc une réduction de risque décisionnel :

1. **Signal Check à 190 EUR HT** pour analyser un rapport, des exports et une configuration existante, sans reproduction du code.
2. **Research Audit à 790 EUR HT** lorsqu'une reproduction, un walk-forward et des stress tests sont nécessaires.
3. **Team Review à 1 900 EUR HT** seulement après deux audits individuels livrés proprement.

Le Signal Check doit rester une porte d'entrée bornée. S'il exige l'exécution du code, la reconstruction des données ou plus d'une stratégie, il bascule vers le Research Audit.

## Client idéal maintenant

Priorité aux personnes qui réunissent au moins quatre de ces cinq signaux :

- stratégie déjà backtestée ou en micro-live ;
- décision proche de mise en production, de montée en capital ou de commercialisation ;
- doute explicite sur l'overfitting, les coûts ou l'exécution ;
- exports ou code disponibles sans transmettre de clé API ;
- capacité à payer pour éviter une mauvaise décision.

Ne pas cibler les débutants sans backtest, les vendeurs de signaux, ni les personnes demandant une garantie de rendement.

## Canal principal

Pendant 14 jours, utiliser un seul canal d'acquisition : les discussions publiques où un auteur demande explicitement une critique méthodologique. Répondre d'abord avec une analyse utile et spécifique. Ne proposer un échange privé que si les règles de la communauté le permettent ou si l'auteur l'invite.

Ordre de priorité vérifié le 2026-08-25 :

1. `Public_Report3194`, francophone, projet macro événementiel, demande explicite de falsification méthodologique, échantillon de 9 à 36 événements.
2. `Prestigious_Ad_8751`, environ 11 000 variantes, Sharpe annoncé doublé après optimisation, invitation explicite au message privé.
3. `mm_mitsuya`, stratégie Pine déjà en micro-live, hésitation avant augmentation du capital.
4. `LowerAd8767`, backtest multi-stratégie de 12 ans et projet de commercialisation.
5. `Internal-Pea-2135`, partenariat potentiel avec une plateforme d'automatisation, à traiter seulement après une première mission payée.

## Première réponse publique recommandée

Réponse au prospect macro francophone, sans lien commercial dans le premier message :

> Votre prudence sur la taille d'échantillon est justifiée. Le risque principal n'est pas seulement d'avoir 9 trades, mais d'avoir choisi le couple événement/instrument après avoir regardé plusieurs réactions. Je figerais d'abord la liste complète des événements et instruments essayés, puis je ferais trois contrôles : données réellement disponibles à l'heure de publication, test placebo sur des fenêtres sans annonce et validation chronologique où aucun seuil n'est retouché. Avec 36 événements, les intervalles d'incertitude et le budget total de variantes comptent davantage que le win rate affiché. Si vous publiez le protocole exact, je peux vous aider à définir un test d'arrêt falsifiable avant d'ajouter de nouveaux paramètres.

Cette réponse démontre la compétence sans vendre immédiatement. Si l'auteur répond avec son protocole ou demande de l'aide, proposer un cadrage privé de 20 minutes et seulement ensuite le Signal Check.

## Sprint quotidien

### Jours 1 à 3

- publier une réponse utile sur les trois prospects prioritaires ;
- enregistrer la date, le lien et la prochaine action dans `founding_audits_pipeline.csv` ;
- ne mettre aucun lien commercial dans la première réponse ;
- répondre aux questions techniques sous 24 heures.

### Jours 4 à 7

- proposer un cadrage privé uniquement aux auteurs ayant répondu ou explicitement invité les messages ;
- qualifier la décision, les données, le nombre de variantes et le budget ;
- envoyer un périmètre écrit d'une page avant tout transfert ;
- demander le paiement avant le début du Signal Check.

### Jours 8 à 14

- livrer la première mission avec un temps suivi ;
- demander un témoignage privé ou public après livraison, sans le conditionner au verdict ;
- publier un enseignement anonymisé uniquement avec autorisation écrite ;
- relancer une seule fois les conversations ouvertes, puis les clôturer.

## Tableau de bord et seuils

| Mesure | Cible à J+7 | Cible à J+14 | Décision |
|---|---:|---:|---|
| Réponses publiques réellement utiles | 3 | 6 | activité sous contrôle direct |
| Conversations qualifiées | 2 | 4 | sinon revoir la cible et le message |
| Cadrages privés | 1 | 3 | sinon renforcer la preuve et le problème traité |
| Propositions écrites | 1 | 2 | aucun travail avant accord |
| Missions payées | 0-1 | 1+ | validation du canal |
| Revenu encaissé | 0-190 EUR | 190 EUR+ | première preuve commerciale |

Après **20 approches contextualisées sans conversation qualifiée**, arrêter ce canal et revoir le positionnement. Après **trois missions payées**, réévaluer les prix, les contrôles récurrents et seulement alors décider s'il existe un produit logiciel répétable.

## Ce qui n'est pas la stratégie

- relancer des milliers de backtests sur BTC, ETH et SOL avec les mêmes sources ;
- promettre qu'une stratégie rentable sera trouvée ;
- acheter de la publicité avant le premier encaissement ;
- construire un portail, un upload client ou un abonnement ;
- envoyer des messages de masse ;
- offrir un audit complet gratuitement.

## Prochaine action externe

La première action est la publication de la réponse française ci-dessus. Elle engage publiquement le nom du fondateur et doit donc être validée juste avant envoi. Le reste du sprint peut être préparé localement sans action externe.

## Repli si Reddit bloque le réseau

Le 2026-08-25, Reddit a renvoyé un blocage de sécurité réseau depuis l'environnement d'exécution. Ne pas contourner ce contrôle et ne pas considérer la réponse comme publiée.

Deux options propres restent disponibles :

1. publier manuellement la réponse préparée depuis une session Reddit autorisée ;
2. publier le retour d'expérience fondateur sur LinkedIn à partir de [`LINKEDIN_LAUNCH_POST.md`](LINKEDIN_LAUNCH_POST.md), puis qualifier uniquement les personnes qui répondent ou écrivent en privé.

Le canal LinkedIn sert à créer de la preuve et des conversations entrantes. Il ne remplace pas les réponses ciblées à une demande explicite et ne doit pas devenir une campagne de messages automatisés.
