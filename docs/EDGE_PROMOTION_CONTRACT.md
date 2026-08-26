# Contrat de promotion du sprint edge

Statut : gelé avant tout résultat forward admissible H-WOF/H-EXE.

Ce contrat distingue trois preuves qui ne sont pas interchangeables :

- H-WOF peut établir un **candidat alpha** après toutes ses gates forward ;
- H-EXE peut établir un **candidat d'amélioration d'exécution**, mais ne peut
  jamais justifier seul une prise de risque de marché ;
- H-QH est rejetée et ne peut être réintroduite dans une promotion.

## Passage à la revue paper

Le statut `candidate_for_paper_review` exige simultanément :

1. production shadow globalement saine, zéro credential et zéro ordre ;
2. H-WOF en `candidate_for_forward_observation` et `REVIEW_REQUIRED` ;
3. reproduction cache-only et reçu CI exacts ;
4. autorisation humaine distincte avant de créer une observation paper.

Ce statut n'autorise pas paper. Il autorise uniquement une décision humaine sur
la création d'une expérience fictive et forward. H-EXE peut être inclus comme
variante d'exécution seulement s'il a lui-même passé ses gates ; sinon le paper
doit employer la baseline conservatrice préenregistrée.

## Passage à la revue micro-live

Le statut `candidate_for_micro_live_review` exige en plus un journal paper :

- lié exactement au digest H-WOF ayant servi à l'admission ;
- au moins quatre semaines complètes ;
- journal et limites de risque préenregistrées vérifiés ;
- PnL net après coûts strictement positif ;
- PnL net stressé strictement positif ;
- aucun dépassement des limites de risque ;
- kill switch testé ;
- zéro credential et zéro ordre pendant cette observation ;
- admission paper humaine explicitement enregistrée.

Même ce statut reste `REVIEW_REQUIRED`. Il n'active ni profil, ni clé, ni flag,
ni boucle. Le preflight live du dépôt, la validation venue, les restrictions de
clé, le triple opt-in de session et une nouvelle autorisation humaine restent
obligatoires.

## Sortie opérationnelle

Le moniteur `check_edge_forward_production.py` expose `edge_promotion` avec les
gates manquantes. En l'absence de preuve paper valide, la valeur live reste
fausse. Toutes les sorties conservent :

```text
authorizes_paper = false
authorizes_live = false
authorizes_orders = false
```
