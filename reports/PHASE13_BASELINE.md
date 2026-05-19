# Phase 13 baseline (Agent 43)

**Date :** 2026-05-19  
**Branche :** `posthackathon/research-lab-phase-3-10`  
**Commit de référence :** `a066001` — feat(research): harden alternative alpha lab phase 12

## Décision

**`proceed_phase13`** — aucun blocage sécurité.

## Git

| Check | Résultat |
|-------|----------|
| Branche active | `posthackathon/research-lab-phase-3-10` |
| `config.yaml` diff | **vide** |
| `src/execution.py` diff | **vide** |
| `src/risk.py` diff | **vide** |
| `src/futures_kraken_cli.py` diff | **vide** |
| Master checkout | **non** |
| `data/collector_cache/*.json` staged | **non** |

## Tests rapides (ciblés Phase 12)

```
tests/test_signal_registry.py tests/test_data_provenance.py tests/test_event_study_oos.py — OK (pré-vol Phase 13)
```

## Pytest (collect-only, post-implémentation)

```
641+ tests attendus après ajouts Phase 13 (voir FINAL_QA_PHASE13.md)
```

## Périmètre Phase 13

- **Mode :** benchmark agentique — volume shock multi-actif (réplication Phase 11), pas alpha sprint.
- **Hypothèse unique :** choc de volume quotidien pré-enregistré → proxy volatilité / risque forward (BTC, ETH, SOL si cache).
- **Autorisé :** rapports, manifest, `--assets` sur `event_study_volume_shock.py`, `--phase13` leaderboard.
- **Interdit :** live, deploy, merge master, nouveau signal, données inventées dans `research_runs_phase13/`.

## Autorisation agents 44–52

Les agents suivants peuvent démarrer sur cette branche tant que les interdictions ci-dessus restent respectées.
