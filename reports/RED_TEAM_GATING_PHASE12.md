# Red team gating — Phase 12

**Branche :** `posthackathon/research-lab-phase-3-10`  
**Source machine :** `reports/red_team_verdicts.json` (dérivé de `RED_TEAM_PHASE11.md`)

## Changements Phase 12

| Avant (Phase 11) | Après (Phase 12) |
|------------------|------------------|
| `lookup_phase11_red_team_status()` codé en dur | `lookup_red_team_status()` + JSON |
| Promotion OOS Wikipedia possible dans l’artefact | `revoked` → cap systématique |
| Placebos volume sur `post_3` | Alignés sur fenêtre BH (`post_7`) |
| `random_timestamps` exchange = copie des cellules | Bootstrap réel `random_events_from_candles` |
| Calendrier Sunday/Monday dupliqué | Alias documenté ; Monday non exécuté |

## Statuts

- **fail / revoked** → `final_verdict` ne peut pas rester `candidate for further OOS testing`.
- **warning** → pas de blocage automatique ; caveats dans le leaderboard.
- **0 PASS** au niveau sprint (inchangé vs Phase 11).

## Rebuild leaderboard

```powershell
python reports/_build_leaderboard.py --phase12
```

**Succès méthodologique attendu :** `oos_candidate_count == 0` avec gates plus stricts.
