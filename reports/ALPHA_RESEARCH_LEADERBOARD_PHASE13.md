# Alpha research leaderboard (Phase 13)

**Généré par :** `reports/_build_leaderboard.py --phase13`
**Périmètre :** volume shock multi-asset (BTC/ETH/SOL) — benchmark agentique.

## Synthèse exécutive

- **Lignes (actif × variante × protocole) :** 27
- **Candidats OOS :** **0** (0 attendu et acceptable)
- **Protocoles agentiques :** `protocol_a`, `protocol_b`, `protocol_c`
- **Signal tradable / live-ready :** **0**

## Leaderboard

| Asset | Variante | Protocole | Events | BH | Placebo | Holdout | Red team | Coûts | Final |
|-------|----------|-----------|--------|----|---------|---------|----------|-------|-------|
| `BTC` | `vol_z20_high` | `protocol_a` | 18 | 3/8 | fail_both_p1 | passed | fail | échec (seuil bru | **weak evidence** |
| `BTC` | `vol_z60_high` | `protocol_a` | 16 | 5/8 | fail_both_p1 | passed | fail | échec (seuil bru | **weak evidence** |
| `BTC` | `vol_z20_range_compression` | `protocol_a` | 0 | 0/0 | not_evaluated | not_run | fail | non évalué | **blocked** |
| `BTC` | `vol_z20_low_abs_return` | `protocol_a` | 0 | 0/0 | not_evaluated | not_run | fail | non évalué | **blocked** |
| `ETH` | `vol_z20_high` | `protocol_a` | 23 | 2/8 | fail_both_p1 | passed | fail | échec (seuil bru | **weak evidence** |
| `ETH` | `vol_z60_high` | `protocol_a` | 15 | 3/8 | fail | passed | fail | échec (seuil bru | **weak evidence** |
| `ETH` | `vol_z20_range_compression` | `protocol_a` | 0 | 0/0 | not_evaluated | not_run | fail | non évalué | **blocked** |
| `ETH` | `vol_z20_low_abs_return` | `protocol_a` | 1 | 0/8 | fail | failed | fail | marginal (recher | **weak evidence** |
| `SOL` | `—` | `protocol_a` | 0 | 0/0 | not_run | not_run | blocked | non évalué | **blocked** |
| `BTC` | `vol_z20_high` | `protocol_b` | 18 | 3/8 | fail_both_p1 | passed | fail | échec (seuil bru | **weak evidence** |
| `BTC` | `vol_z60_high` | `protocol_b` | 16 | 5/8 | fail_both_p1 | passed | fail | échec (seuil bru | **weak evidence** |
| `BTC` | `vol_z20_range_compression` | `protocol_b` | 0 | 0/0 | not_evaluated | not_run | fail | non évalué | **blocked** |
| `BTC` | `vol_z20_low_abs_return` | `protocol_b` | 0 | 0/0 | not_evaluated | not_run | fail | non évalué | **blocked** |
| `ETH` | `vol_z20_high` | `protocol_b` | 23 | 2/8 | fail_both_p1 | passed | fail | échec (seuil bru | **weak evidence** |
| `ETH` | `vol_z60_high` | `protocol_b` | 15 | 3/8 | fail | passed | fail | échec (seuil bru | **weak evidence** |
| `ETH` | `vol_z20_range_compression` | `protocol_b` | 0 | 0/0 | not_evaluated | not_run | fail | non évalué | **blocked** |
| `ETH` | `vol_z20_low_abs_return` | `protocol_b` | 1 | 0/8 | fail | failed | fail | marginal (recher | **weak evidence** |
| `SOL` | `—` | `protocol_b` | 0 | 0/0 | not_run | not_run | blocked | non évalué | **blocked** |
| `BTC` | `vol_z20_high` | `protocol_c` | 18 | 3/8 | fail_both_p1 | passed | fail | échec (seuil bru | **weak evidence** |
| `BTC` | `vol_z60_high` | `protocol_c` | 16 | 5/8 | fail_both_p1 | passed | fail | échec (seuil bru | **weak evidence** |
| `BTC` | `vol_z20_range_compression` | `protocol_c` | 0 | 0/0 | not_evaluated | not_run | fail | non évalué | **blocked** |
| `BTC` | `vol_z20_low_abs_return` | `protocol_c` | 0 | 0/0 | not_evaluated | not_run | fail | non évalué | **blocked** |
| `ETH` | `vol_z20_high` | `protocol_c` | 23 | 2/8 | fail_both_p1 | passed | fail | échec (seuil bru | **weak evidence** |
| `ETH` | `vol_z60_high` | `protocol_c` | 15 | 3/8 | fail | passed | fail | échec (seuil bru | **weak evidence** |
| `ETH` | `vol_z20_range_compression` | `protocol_c` | 0 | 0/0 | not_evaluated | not_run | fail | non évalué | **blocked** |
| `ETH` | `vol_z20_low_abs_return` | `protocol_c` | 1 | 0/8 | fail | failed | fail | marginal (recher | **weak evidence** |
| `SOL` | `—` | `protocol_c` | 0 | 0/0 | not_run | not_run | blocked | non évalué | **blocked** |

## Références

- `reports/research_runs_phase13/RUN_LOG_PHASE13.md`
- `reports/RED_TEAM_PHASE13.md`
- Rebuild : `python reports/_build_leaderboard.py --phase13`
