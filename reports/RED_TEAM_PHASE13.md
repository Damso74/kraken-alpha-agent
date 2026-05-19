# Red team Phase 13 (Agent 49)

**Date :** 2026-05-19  
**Scope :** volume shock multi-asset — protocoles A, B, C

## Verdict global

**`no_oos_retained`** · **`weak_evidence_only`** · **`partial_assets_available`**

## Checklist (15 points)

| # | Question | Résultat |
|---|----------|----------|
| 1 | Même hypothèse sur les 3 protocoles ? | **pass** (même JSON) |
| 2 | Actifs comparables ? | **warning** (SOL absent) |
| 3 | Horizons identiques ? | **pass** |
| 4 | Placebos alignés ? | **pass** (post_7) mais **fail** (p=1) |
| 5 | Hold-out respecté ? | **pass** (activé) · **fail** (survie) |
| 6 | Signal trop rare ? | **warning** (certaines variantes 0 evt) |
| 7 | Un actif domine ? | **warning** (BTC plus documenté historiquement) |
| 8 | Une période domine ? | **warning** (non testé LOMO) |
| 9 | Cost dominated ? | **pass** (non tradable) |
| 10 | Vol seulement vs return ? | **pass** (effet surtout vol/DD) |
| 11 | Confusion proxy vs trading ? | **warning** (builder B) |
| 12 | Provenance complète ? | **pass** BTC/ETH |
| 13 | Agents hors scope ? | **pass** (pas execution/risk/web) |
| 14 | Claims interdits ? | **pass** |
| 15 | Surproduction code ? | **pass** (diff minimal) |

## Par protocole

| Protocole | Statut | Raison |
|-----------|--------|--------|
| A single-agent | **pass** | Verdict faible honnête |
| B builder+RT | **pass** | RT plus conservateur que builder |
| C committee | **pass** | Refus explicite promotion |

## Veto

Tout `candidate for further OOS testing` est **bloqué** (red team volume_shock fail + hold-out + placebos).

## Recommandation

**`stop_research`** sur promotion ; continuer benchmark agentique en Phase 14 avec Protocol C pour hypothèses sensibles.
