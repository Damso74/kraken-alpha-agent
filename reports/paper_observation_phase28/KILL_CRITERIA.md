# Phase 28 — Kill criteria (overlay paper observation)

> Observation-only. Aucun ordre live. Flag d'arrêt : `reports/paper_observation_phase28/STOP_OBSERVATION`.

## Seuils par défaut (`OverlayKillConfig`)

| Critère | Seuil | Action |
|---------|-------|--------|
| Taux de block sur signaux standalone | > **60%** sur fenêtre glissante 30 barres | Kill |
| Trades paper insuffisants | < **5** trades après ≥30 shadow rows | Kill |
| Blocks incohérents | ≥ **3** blocks sans funding_z ≥1.5 ni basis_z ≥1.5 | Kill |
| Underperformance vs standalone | gap rolling **< −5 pp** sur 30 barres | Kill |
| Données derivatives stale | basis manquant alors que mode `funding_basis` | Kill (flag stale) |
| Flag manuel | fichier `STOP_OBSERVATION` présent | Kill immédiat |

## Interprétation

- **Blocks trop fréquents** : l'overlay neutralise la stratégie sans laisser assez de trades pour juger le filtre crowding.
- **Upside manqué sans réduction DD** : détecté via shadow comparison + equity gap ; si l'overlay bloque/réduit sans améliorer le drawdown paper, observation arrêtée.
- **Décisions incohérentes** : block sans crowding extrême (funding/basis z modérés) = bug de classification ou mauvaise alignement cache.
- **Stale data** : funding-only fallback quand basis cache absent en mode `funding_basis` → warning + kill si persistant.

## Procédure

1. Le daemon évalue `evaluate_overlay_kill()` à chaque cycle `--mode once|loop`.
2. Si kill → écrit `STOP_OBSERVATION` avec raisons concaténées.
3. Cycles suivants retournent `{"status": "stopped"}` sans modifier l'état paper.
4. Pour reprendre : supprimer manuellement `STOP_OBSERVATION` après correction (cache rebuild, param review).

## Non-objectifs

- Ces critères **ne déclenchent pas** micro-live.
- Ils **n'appellent jamais** `execution.py` ni l'API Kraken privée.
