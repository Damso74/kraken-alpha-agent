# Agentic research benchmark (Phase 13)

## Objectif

Comparer **trois protocoles multi-agent** sur **une seule hypothèse** pré-enregistrée :

> Un choc de volume quotidien (z ≥ 2, variantes Phase 11) est-il un proxy robuste de volatilité future ou de risque sur plusieurs actifs crypto — **sans** prétention directionnelle ni tradabilité ?

Le KPI n’est pas le PnL ni le nombre de fichiers créés, mais la **qualité du verdict** et la capacité à **refuser une promotion OOS abusive**.

## Protocoles comparés

| ID | Nom | Rôles | Avantage | Risque |
|----|-----|-------|----------|--------|
| **A** | Single-agent | Un agent : données → event study → verdict | Rapide, diff minimal | Biais non contestés |
| **B** | Builder + red team | Builder produit ; red team attaque | Bon compromis coût / rigueur | Dépend de la qualité du RT |
| **C** | Full committee | Data, Builder, Sceptic, Economist, Repro, PM | Verdict le plus conservateur | Latence, sur-documentation |

## Grille de scoring agentique (/10 chacun)

1. Respect du scope  
2. Fichiers modifiés (moins = mieux si verdict équivalent)  
3. Simplicité  
4. Tests ajoutés (utiles seulement)  
5. Bugs évités  
6. Qualité provenance données  
7. Qualité placebos (alignés BH / fenêtre)  
8. Qualité red team  
9. Clarté du verdict  
10. Capacité à dire non  
11. Contrôle overengineering  

**Score total max :** 110 par protocole (voir `reports/AGENTIC_PERFORMANCE_PHASE13.json`).

## Métriques de recherche (communes aux trois protocoles)

- Actifs testés vs bloqués  
- Événements par actif / variante  
- Cellules BH rejetées  
- Placebos shift +30j / shuffle (alignés `post_7` return ou vol selon cellule primaire)  
- Hold-out G4 (fraction 0,5, embargo 7 j policy)  
- Verdict coûts / concentration / régime (overlay existant)  
- Verdict final (jamais tradable / live-ready)

## Règles de promotion

- **0 OOS = succès** pour ce benchmark.  
- Red team `fail` / `revoked` → pas de candidat OOS.  
- Hold-out raté → pas de candidat OOS.  
- Provenance manquante → pas de candidat OOS.  
- SOL (ou tout actif) sans cache → `blocked_data`, pas de données inventées.

## Références

- Protocoles détaillés : `reports/AGENTIC_PROTOCOLS_PHASE13.md`  
- Performance agents : `reports/AGENTIC_PERFORMANCE_PHASE13.md`  
- Signal leaderboard : `reports/ALPHA_RESEARCH_LEADERBOARD_PHASE13.md`
