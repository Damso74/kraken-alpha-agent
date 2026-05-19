# Agentic performance leaderboard (Phase 13)

**Généré :** Agent 51 — comparaison des protocoles A / B / C

## Scores (/110)

| Protocole | Scope | Minimal diff | Data | Tests | Placebos | RT | Repro | Clarté | Dire non | Anti-OE | **Total** |
|-----------|-------|--------------|------|-------|----------|-----|-------|--------|----------|---------|-----------|
| **A** single-agent | 9 | 10 | 8 | 7 | 8 | 6 | 9 | 8 | 7 | 9 | **81** |
| **B** builder+RT | 9 | 9 | 8 | 7 | 9 | **10** | 9 | 9 | **9** | 8 | **87** |
| **C** committee | 8 | 7 | 9 | 7 | 9 | 9 | 10 | **10** | **10** | 7 | **86** |

## Recommandation Phase 14

| Situation | Protocole recommandé |
|-----------|---------------------|
| Hypothèse simple, smoke / cache check | **A** |
| Hypothèse standard, bon compromis | **B** |
| Hypothèse data-heavy ou proche OOS | **C** |

**Règle opérationnelle :** le comité complet (C) est plus lent mais **réduit les faux positifs** ; le single-agent (A) est acceptable uniquement si le verdict reste « weak / blocked » sans contestation.

## Limites

- Scores qualitatifs issus des rapports Phase 13, pas d’auto-ML.  
- Même run JSON sous-jacent — la comparaison porte sur la **gouvernance**, pas sur des alpha différents.
