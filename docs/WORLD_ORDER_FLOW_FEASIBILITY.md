# Audit de faisabilité causale — H-WOF-002

Date de gel : 26 août 2026  
Verdict historique actuel : **NO-GO données, fail-closed**

## Question auditée

Peut-on répliquer proprement un signal hebdomadaire cross-sectionnel de « world
order flow » sur 30 à 80 crypto-actifs, sans utiliser l'univers de cotation
actuel pour reconstruire le passé ?

## Ce qui est disponible

- Les klines publiques Binance 1d fournissent `quote volume` et
  `taker-buy quote volume`, suffisants pour le proxy agrégé pré-enregistré.
- Les archives Binance Vision `aggTrades` permettent un audit d'équivalence
  borné, mais sont trop volumineuses pour constituer raisonnablement le corpus
  multi-actifs multi-années de cette expérience.
- L'endpoint public `exchangeInfo` fournit l'univers Spot actuellement connu et
  son statut au moment de la requête.
- Les prix d'entrée et de sortie peuvent être collectés séparément sur Kraken
  pour les actifs effectivement négociables au moment de la décision.

## Lacune bloquante

Binance Vision ne publie pas, dans ce corpus, une série officielle et complète
de snapshots historiques `exchangeInfo`. Un snapshot téléchargé en 2026 ne
prouve donc pas qu'un actif était éligible en 2022, 2023, 2024 ou 2025. Partir
de la liste actuelle produirait un biais de survivants et ne satisfait pas la
spécification H-WOF-002.

La présence d'un fichier de transactions prouve qu'une paire a échangé pendant
un mois ; elle ne suffit pas à reconstruire causalement l'ensemble des actifs
qui auraient dû être classés à chaque semaine. L'absence d'un fichier ne permet
pas non plus de distinguer une paire inexistante, suspendue ou une archive
indisponible.

## Décision d'architecture

Le collecteur implémenté sépare donc strictement :

1. un journal append-only de snapshots `exchangeInfo`, utilisable uniquement
   pour des décisions postérieures à la date d'observation ;
2. des klines 1d collectées causalement, sans interpolation ;
3. un petit échantillon `aggTrades` immuable, lié à un SHA-256 attendu, réservé
   au diagnostic d'équivalence du proxy ;
4. un harnais qui exclut une semaine entière si un membre de l'univers causal
   n'a pas à la fois son flux complet et ses prix exécutables ;
5. un verrou final qui refuse 2026 tant que la validation historique n'a pas
   passé toutes les gates avec le même pré-enregistrement et le même code.

## Approximation par rapport à l'article

H-WOF-002 n'est pas une réplication tick-exacte du papier : elle remplace le
flux mondial multi-places par le déséquilibre agrégé des klines Binance Spot.
Avant toute conclusion, un audit borné doit comparer ce score à l'agrégation
`aggTrades` sur les deux actifs et le jour pré-définis dans le pré-enregistrement.
Le résultat de cet
audit est diagnostique ; il ne permet pas de choisir post-hoc une autre formule.

## Condition pour rouvrir l'historique

Une validation 2024–2025 n'est autorisée que si un registre point-in-time
vérifiable est fourni pour toute la fenêtre : snapshots capturés à l'époque,
archives tierces avec dates de disponibilité et licence explicites, ou série
officielle équivalente. Chaque snapshot doit précéder le début de la semaine
qu'il gouverne et sa provenance doit être hashée.

À défaut, H-WOF-002 reste une expérience **forward uniquement**. Aucun résultat
issu d'un univers actuel rétro-projeté ne peut être qualifié d'edge, de
validation OOS ou de candidat au paper/live.

## Sources

- Binance Public Data :
  <https://github.com/binance/binance-public-data/blob/master/README.md>
- Binance Spot REST API (`exchangeInfo`, `aggTrades`) :
  <https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md>
- Article de référence : <https://doi.org/10.1016/j.finmar.2026.101047>
