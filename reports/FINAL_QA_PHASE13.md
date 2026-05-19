# Final QA Phase 13 (Agent 52)

**Date :** 2026-05-19  
**Branche :** `posthackathon/research-lab-phase-3-10` @ `a066001` (+ changements Phase 13 non commités)

## 1. Résumé exécutif

Phase 13 **terminée** : benchmark agentique volume shock multi-actif (BTC/ETH OK, SOL `blocked_data`), **0 candidat OOS**, protocole **B (builder + red team)** recommandé pour le quotidien, **C** près des frontières OOS. Aucun impact live ; `config.yaml` et moteurs trading inchangés.

## 2. Branche / commit

| Item | Valeur |
|------|--------|
| Branche | `posthackathon/research-lab-phase-3-10` |
| Base | `a066001` |
| Merge master | **non** |
| Deploy | **non** |

## 3. Fichiers créés (principaux)

- `reports/PHASE13_BASELINE.md`
- `docs/AGENTIC_RESEARCH_BENCHMARK.md`
- `reports/AGENTIC_PROTOCOLS_PHASE13.md`
- `reports/DATA_AUDIT_MULTI_ASSET_PHASE13.md`
- `reports/data_manifests_phase13/ohlcv_multi_asset_manifest.json`
- `reports/research_runs_phase13/*.json`, `RUN_LOG_PHASE13.md`
- `reports/protocol_a_single_agent/`, `protocol_b_builder_red_team/`, `protocol_c_full_committee/`
- `reports/RED_TEAM_PHASE13.md`
- `reports/ALPHA_RESEARCH_LEADERBOARD_PHASE13.{md,json}`
- `reports/AGENTIC_PERFORMANCE_PHASE13.{md,json}`
- `reports/agent_scores_phase13/`
- `tests/test_leaderboard_phase13.py`

## 4. Fichiers modifiés (code minimal)

- `scripts/event_study_volume_shock.py` — `--assets`, hold-out, provenance multi-actif
- `reports/_build_leaderboard.py` — `--phase13`
- `src/data/collectors/_provenance.py` — `safe_git_commit`, `ohlc_cache_row_count`
- `tests/test_data_provenance.py` — tests nested cache

## 5. Tests

```
646 collected — 646 passed
```

## 6. Leaderboard signal

```
python reports/_build_leaderboard.py --phase13
Rows: 27 ; OOS candidates: 0
```

## 7. Leaderboard agents

`reports/AGENTIC_PERFORMANCE_PHASE13.json` — B=87, C=86, A=81 /110.

## 8. Red team

`reports/RED_TEAM_PHASE13.md` — veto OOS ; `no_oos_retained`.

## 9. Verdict signal

**weak evidence** (BTC/ETH) · **blocked** (variantes vides / SOL data).

## 10. Verdict agentique

**Protocol B** pour hypothèses standard ; **Protocol C** si risque de sur-promotion.

## 11. Risques restants

- Cache SOL non fourni (partial multi-asset).  
- Embargo 7j appliqué dans `holdout.py` (`apply_embargo`) ; métadonnées
  `embargo_days_requested` / `embargo_days_applied` dans les JSON hold-out.  
- Volume shock toujours **fail** dans `red_team_verdicts.json`.

## 12. Recommandation

- **Prêt à commit** sur branche `posthackathon` (si l’utilisateur le demande).  
- **Ne pas merger master** avant jugement hackathon.  
- **Aucun deploy / live.**
