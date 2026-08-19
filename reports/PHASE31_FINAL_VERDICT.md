# Phase 31 — Verdict final

**Date :** 2026-08-19
**Branche :** `phase30/observation-ops-ux`
**Portée :** clôture du laboratoire de recherche post-hackathon (phases 3 à 30)

---

## Décision

### **`research_closed`**

| Gate | Statut |
|------|--------|
| Signal tradable identifié | **0** |
| Candidat out-of-sample | **0** |
| Overlay retenu | **0** — le seul survivant ne passe pas l'audit de ses données |
| Observation forward | **archivée** (jamais démarrée : 1 barre au 2026-05-21, 0 depuis) |
| Micro-live | **NO-GO** (inchangé — PEDSL-CY, cf. ADR-003) |
| Reprise d'une phase 32 sur le même univers | **non recommandée** |

Ce document remplace `reports/PHASE30_NEXT_DECISION.md` comme dernière décision
en date. `reports/PHASE31_REVIEW_CHECKLIST.md` reste au dépôt comme protocole
**non exécuté**.

---

## 1. Ce que la recherche a réellement établi

Un résultat négatif large, cohérent, et **répété sur trois pipelines
indépendants** :

| Pipeline | Volume | Survivants |
|----------|--------|-----------|
| Moteur / walk-forward OOS | 872 configurations | **0** |
| Event studies (hypothèses alternatives) | 18 hypothèses au board | **0** candidat OOS, **0** rejet BH-FDR |
| Tournois de stratégies / walk-forward bot | ~600 runs | **0** candidat papier |

La convergence de trois méthodes distinctes vers zéro est le résultat solide de
ce dépôt. Il tient.

**Ce qui l'a tué, couche par couche.** Le rejet ne vient pas d'une seule barrière
mais de leur empilement — et c'est ce qui le rend crédible :

- **G0 — puissance.** Les tailles d'échantillon sont insuffisantes partout où le
  signal est positif, et suffisantes seulement là où il est nul. Event studies :
  n = 0, 2, 16, 18, 23, 29, 105, 129. Backtests : médiane de 9,5 trades en
  phase 23, 55 trades sur trois ans en phase 24, 27 en phase 25. Le seul grand N
  du corpus, `funding_extreme` avec n = 3 143, affiche un `sign_rate` de 0,50 à
  0,51 — soit exactement le hasard.
- **G1 — inférence.** Aucune hypothèse exécutée ne survit à Benjamini-Hochberg
  sur le rendement post-7 jours.
- **G3 — réalisme économique.** Round-trip pessimiste retenu : **1,00 %** sur
  Kraken spot. 5 signaux évalués sur 5 sont rejetés comme *economically
  impossible*.
- **G4 — out-of-sample.** `oos_candidate_count: 0`, conformément à la politique
  anti-curve-fit.

**Ce qui n'est pas mort par les coûts.** Nuance importante et contre-intuitive :
la grille de sensibilité aux frais de la phase 22 (972 runs) donne 22 cellules
`no_edge_at_zero_fees` et **0 cellule `killed_by_costs`**. Les stratégies
testées n'ont pas d'edge *même à frais nuls*. Les coûts ne sont donc pas
l'explication du zéro — ils ne font que fermer la porte à des marges qui de toute
façon n'existaient pas.

---

## 2. Ce que l'audit de clôture a changé

L'audit du 2026-08-19 (six analyses parallèles, chaque constat majeur soumis à un
vérificateur adversarial) a examiné le seul objet que 30 phases n'avaient pas
tué : l'**overlay de risque funding + basis ETH 4h**, classé `useful_overlay`.

Il ne survit pas. Quatre défauts, tous vérifiés dans le code :

**a) Le cache funding était tronqué à une page.** Les quatre bundles de
`reports/phase26_event_studies/summary.json` annoncent tous `"funding_rows": 1000`
— exactement la valeur de `FUNDING_PAGE_LIMIT` dans
`src/data/collectors/binance_derivatives_public.py`. La fenêtre de backtest
ETH 4h couvre ~1 100 jours, soit ~2 190 points de funding à raison d'un toutes
les 8 heures. La pagination s'arrêtait après la première page, et elle couvrait
le **début** de la fenêtre, pas la fin.

**b) Le forward-fill n'était pas borné.** Au-delà de la fin du cache,
`src/bot/crowding_overlay.py` rendait indéfiniment la dernière valeur connue. Sur
une série devenue constante, `pstdev` vaut zéro et le z-score vaut exactement
`0.0`. Toutes les branches bloquantes de `basis_crowding_overlay.py` devenaient
alors inatteignables : l'overlay dégénérait silencieusement en basis-only sur
~70 % de la fenêtre, et le journal affichait `neutral` là où la vérité était
`no_data`.

**c) Le pipeline dérivés n'appliquait aucun test d'inférence.** Contrairement aux
phases 6 à 13, `src/bot/derivatives_event_study.py` ne contenait ni p-value, ni
placebo, ni correction BH-FDR. Son unique filtre était un seuil brut non
pré-enregistré de 0,15 pp, appliqué **en valeur absolue** : un excès *négatif*
comptait comme preuve favorable. Sur ETH 4h, deux des trois « signaux non
triviaux » retenus l'étaient par excès négatif (−1,12 et −1,53 pp) sur n = 9 à 11.
Le gate `proceed_to_overlay` rendait `true` sur 4 bundles sur 4.

**d) Un défaut découvert en fin d'audit, plus lourd que tous les autres : le risk
manager du moteur de recherche refusait les sorties de position.**

`src/bot/risk_manager.py` appliquait cinq de ses garde-fous — `max_position_fraction`,
`max_total_exposure`, `max_trades_per_day`, `max_drawdown_pct`, `max_daily_loss_pct` —
aux ordres de **vente** comme aux ordres d'achat. Or dans ce moteur une vente ne peut
que réduire l'exposition : le short est impossible à trois niveaux (`paper_engine`
clampe la quantité, `execution_simulator` rejette `insufficient_position`,
`PaperPortfolio` lève). Conséquence : dès qu'une position dépassait le plafond après
une hausse de prix, ou dès qu'un stop de drawdown se déclenchait, **toute sortie était
refusée**. Le stop censé couper le risque piégeait la position au lieu de la solder.

Mesure end-to-end sur une série synthétique, `max_position_fraction=0.20` (le preset
4h réel), hausse de +25 % entre l'entrée et la sortie :

| | avant | après |
|---|---|---|
| `trade_count` | 1 (la vente n'est jamais exécutée) | 2 |
| `risk_denials` | 20 / 21 | 0 / 21 |
| `final_equity` | 1067,37 | 1044,57 |

Ampleur réelle dans les artefacts déjà produits, par comptage des règles effectivement
déclenchées dans `reports/**/*.json` : `max_drawdown_pct` **966 fois**,
`max_position_fraction` **874**, `max_daily_loss_pct` **150**, `max_trades_per_day`
**41**. Et sur les `risk_denial_rate` stockés : 557 runs à 0,0, mais **216 runs à
exactement 1,0** — la signature d'une position piégée refusée à chaque barre. Un taux
de refus de 0,95 dépasse `MAX_RISK_DENIAL_RATE` et faisait basculer le run en
`blocked_risk` : des stratégies ont donc été rejetées pour une raison qui n'existait pas.

**Ce que cela change pour le verdict — et ce que cela ne change pas.** Le biais n'est
pas uniformément pessimiste : en tendance haussière, une position qu'on ne peut pas
solder continue de monter en valeur latente et bat la sortie réelle ; sur un
retournement l'effet s'inverse violemment. Il est donc **corrélé au régime de la
période testée**, ce qui interdit l'argument « le rejet est valide *a fortiori* ».

Le résultat négatif tient néanmoins, pour une raison indépendante : la grille de
sensibilité aux frais de la phase 22 donne **0 cellule `killed_by_costs` et 22
cellules `no_edge_at_zero_fees`**. L'absence d'edge est constatée *avant* toute
mécanique d'exécution. Mais il faut le dire clairement : les chiffres par run des
phases 14 à 30 ne sont pas fiables, et le verdict repose désormais sur la convergence
des méthodes et sur l'absence d'edge brut, pas sur la valeur de tel ou tel backtest.

**Conclusion.** Le compte n'est pas « 0 alpha + 1 overlay utile ». Il est **0**.
Le verdict `useful_overlay` reposait sur une comparaison funding+basis contre
funding-only dont le leg funding était mort sur la majorité de la fenêtre, validée
par un gate qui n'excluait rien, sur des backtests dont les positions ne pouvaient
pas être soldées.

---

## 3. L'observation forward n'a jamais eu lieu — et n'aurait rien mesuré

La phase 30 avait conclu `ready_for_vps_cron` le 2026-05-21. Le cron n'a jamais
été installé. Trois mois plus tard : **1 barre au 2026-05-21, 0 aujourd'hui**,
healthcheck `FAIL`, `Cron active: False`. L'état d'exécution étant gitignore, rien
n'a survécu.

Les « 114 trades » et le « block rate 0 % » des rapports des phases 28-29 ne sont
pas de l'observation forward : ce sont des **replays du cache historique**.

Plus grave, le harnais de mesure était lui-même défectueux. Dans
`src/bot/overlay_observation_engine.py`, la boucle de replay avait un corps vide :

```python
for i in range(warmup, bar_index):
    portfolio_standalone   # expression morte — ruff B007 + B018
```

Le portefeuille standalone restait donc vide. Or `trend_following` et
`ema_crossover` conditionnent leur `sell` à `pos.quantity > 1e-12` et leur `buy` à
`pos.quantity <= 1e-12` : avec un portefeuille toujours vide, le baseline **ne
pouvait jamais vendre**, et achetait à chaque barre haussière au lieu du seul
croisement. Le « standalone » auquel l'overlay était comparé n'était pas la
stratégie standalone. Par ricochet, le critère de kill `too_few_trades` devenait
du code mort et `block_rate_on_signals` changeait de définition — or c'est
précisément la métrique qui devait alimenter la revue J+7 / J+14.

Un cinquième critère de kill, « underperformance vs standalone », était
structurellement inerte : ses deux appelants omettaient l'argument de rendement
standalone, et l'alerte de secours était gardée par une condition dont la valeur
était codée en dur à `None`.

**Relancer le cron aurait donc collecté quatorze jours de mesures fausses sur un
overlay dont les données d'entrée étaient déjà fausses, avec un critère d'arrêt
sur cinq incapable de se déclencher.** C'est la raison de l'archivage (ADR-012),
et non un simple arbitrage de coût.

---

## 4. La seule piste encore ouverte, et pourquoi elle est fermée aussi

Un signal du corpus mérite d'être nommé parce qu'il est le seul à cocher les
critères que tous les autres ratent : `funding_zscore` avec |z| ≥ 2 comme signal
directionnel autonome.

| | n | excès 24h | excès 48h | excès 72h | sign_rate |
|---|---|---|---|---|---|
| ETH 4h | 142 | +0,155 pp | +0,637 pp | +0,786 pp | 0,521 / 0,641 / 0,606 |
| BTC 4h | 126 | +0,040 pp | +0,482 pp | +0,931 pp | 0,548 / 0,564 / 0,564 |

C'est le seul signal du dépôt avec n > 100, un excès positif **monotone en
horizon**, et une cohérence entre deux actifs. Il n'a jamais été soumis à
placebo, BH-FDR ni hold-out, ni utilisé comme signal d'entrée.

Il est néanmoins fermé, et par arithmétique plutôt que par statistique :
**+0,79 pp à 72 h contre 1,00 % de round-trip pessimiste donne un net de
−0,21 pp**. Le signal est mort par construction sur ce venue, quelle que soit sa
significativité. Le tester proprement reste possible — les gates d'inférence
manquants ont été ajoutés au pipeline dans le cadre de cette clôture — mais le
résultat attendu est `cost dominated`, pas `not supported`.

---

## 5. Ce qui a été corrigé à la clôture, et pourquoi

Le code fautif ne devait pas rester en référence dans un dépôt public. Les
correctifs suivants ont été appliqués **bien que la recherche soit close** :

| Défaut | Correctif |
|--------|-----------|
| CI jamais exécutée (`ruff` absent de `requirements.txt`, `exit 127`) | `ruff` déclaré ; `bash -n` + `shellcheck` sur les scripts d'ops ; `git diff --exit-code` après pytest |
| Rapport de recherche réécrit par une fixture pytest | Le markdown suit `--report-dir` ; rapport régénéré depuis sa source JSON ; test de non-régression |
| **Risk manager refusant les sorties** (5 garde-fous appliqués aux ventes) | Un plafond contraint l'ouverture d'exposition, jamais sa réduction |
| Boucle de replay no-op | Replay réel du portefeuille standalone |
| Critère de kill inerte | Rendement standalone propagé, ou impossibilité rendue explicite |
| Pagination funding tronquée | Pagination corrigée + avertissement si le total est un multiple exact de la page |
| Forward-fill non borné | Borne de fraîcheur ; `no_data` distinct de `neutral` |
| Aucun test d'inférence sur les dérivés | Bootstrap + BH-FDR + plancher de puissance + seuil directionnel |
| Placebo phase 25 à la règle inversée | Orientation corrigée (le verdict `kill` final reste inchangé) |
| `win_rate` à 0 avec 55 trades | Absence d'information rendue explicite plutôt que confondue avec un échec |
| `cost_drag` à 100 % par valeur sentinelle | Valeur non définie distinguable d'une mesure |
| `_check_interval_spacing` inerte | Vérifie réellement l'espacement des bougies |
| Caches non reproductibles | `scripts/reseed_collector_cache.py` — reconstruction vérifiée par sha256 depuis les manifests |
| 840 erreurs ruff | 910 corrections mécaniques, reliquat traité au cas par cas |
| Pollution CRLF (clone vierge sale) | `git add --renormalize` |

**Ce qui n'a délibérément pas été fait.** La dette architecturale — les deux
paradigmes de stratégie fusionnés dans les mêmes fichiers, le cycle d'imports
`src.bot` ↔ `src.strategies`, les 117 lignes de transport dupliquées, la fonction
`evaluate_risk` de 279 lignes — n'a pas été traitée. Ce sont des coûts de
maintenance future, pas des défauts actifs. Les traiter maintenant reviendrait à
investir dans un code qui ne tournera plus. Ils sont documentés pour un éventuel
repreneur.

De même, aucune mesure de couverture n'a été mise en place : elle ne servirait
qu'un développement continu.

---

## 6. Limites de ce verdict — ce qu'il ne prouve pas

Par honnêteté méthodologique, et parce que c'est la seule posture cohérente avec
le reste du dépôt :

1. **Le budget de tests cumulé n'a jamais été corrigé.** Plus de 2 600
   configurations de backtest et 872 configurations moteur ont été évaluées sur
   essentiellement la même donnée, sur la même fenêtre. Les corrections BH
   portent sur 5 à 8 cellules à l'intérieur d'un run isolé, jamais sur la série.
   Le risque pratique est faible ici — le résultat est nul, et le data snooping
   fabrique des faux positifs, pas des faux négatifs — mais il aurait été
   disqualifiant si un candidat avait émergé.
2. **Croisement de venues.** Les OHLC utilisés sont Binance spot, la grille
   tarifaire appliquée est celle de Kraken. Sans conséquence pour un verdict
   négatif (le rejet est valide *a fortiori*), disqualifiant pour tout verdict
   positif futur.
3. **Le plancher de puissance officiel était trop bas.** `SIGNAL_REJECTION_POLICY`
   exigeait n ≥ 5 quand les red teams internes exigeaient n ≥ 30 à 40 — presque
   un ordre de grandeur d'écart. Relevé à la clôture.
4. **« 0 paper_candidate sur 432 runs » en phase 24 est tautologique** :
   `PHASE24_PAPER_CANDIDATE_FORBIDDEN = True` interdit structurellement le
   verdict positif. Le garde-fou est légitime, mais la preuve non tautologique du
   zéro vient des phases 17 (54 runs), 21 (81 walk-forwards) et 23 (48 runs) —
   ce sont celles-là qu'il faut citer.
5. **Aucun résultat des phases 21 à 30 n'était reproductible depuis un clone**
   avant l'ajout de `scripts/reseed_collector_cache.py`. Les manifests portaient
   les sha256 mais pas le moyen de reconstruire les caches.

---

## 7. Le blocage venue détermine le résultat

Fait établi, et il conditionne la lecture de tout ce qui précède : le compte est
en classe **PEDSL-CY** (Chypre, UE), ce qui bloque au niveau venue le spot
xStocks *et* les xStocks Perpetual Futures (ADR-003).

Avec un round-trip de 1,00 % sur Kraken spot, **aucune des pistes identifiées
dans ce dépôt ne peut être nette positive** — la meilleure, `funding_zscore` à
72 h, est mécaniquement négative après coûts. Sur un venue à ~10 bps aller-retour,
le calcul changerait de signe.

Autrement dit, le blocage n'est pas seulement un obstacle d'accès : il **détermine
le résultat** de toute la recherche menée. Un changement de venue rouvrirait la
question, mais ce serait alors un **projet différent** — autre univers de données,
autre microstructure, backtest entièrement à refaire.

Ce document ne formule aucune recommandation d'investissement et n'est pas un
conseil financier. Il constate que rien dans ce dépôt ne constitue aujourd'hui un
edge exploitable, sur aucun venue, et qu'en changer ne rendrait pas exploitables
les résultats existants.

---

## 8. Si quelqu'un reprend ce dépôt

Dans cet ordre :

1. Lire ce document, puis `reports/RESEARCH_DECISION_BOARD.md` et
   `docs/METHODOLOGY.md`. Ne pas relancer une phase avant.
2. `pip install -r requirements.txt && pytest` — la suite doit être verte, et la
   CI aussi. Si elle ne l'est pas, c'est le premier chantier.
3. Ne pas réinstaller le cron d'observation (ADR-012). Le harnais est corrigé
   mais l'objet observé ne vaut pas l'observation.
4. Pour reproduire un résultat chiffré :
   `python scripts/reseed_collector_cache.py --dry-run` d'abord, puis sans
   `--dry-run`, et vérifier les sha256 contre les manifests.
5. Toute nouvelle hypothèse doit être **pré-enregistrée** (seuil et horizon gelés
   avant exécution) et passer G0 à G4 tels que décrits dans
   `docs/SIGNAL_REJECTION_POLICY.md`. Le pipeline dérivés y est désormais soumis
   comme les autres.

---

## Références

- Décisions : `docs/DECISIONS.md` — ADR-012 (archivage), ADR-013 (CI), ADR-014 (clôture)
- Board des hypothèses : `reports/RESEARCH_DECISION_BOARD.md`
- Méthodologie : `docs/METHODOLOGY.md`, `docs/SIGNAL_REJECTION_POLICY.md`
- Décision précédente : `reports/PHASE30_NEXT_DECISION.md`
- Protocole non exécuté : `reports/PHASE31_REVIEW_CHECKLIST.md`
- Qualité et CI : `docs/QUALITY.md`
