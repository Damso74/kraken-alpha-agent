# Red team — Phase 29 observation ops

**Date :** 2026-05-21  
**Scope :** Phase 28 daemon + Phase 29 monitoring aggregator

## 1. Live / ordres réels / API privée Kraken

| Check | Verdict | Evidence |
|-------|---------|----------|
| Aucun import `execution.py` | PASS | `run_overlay_observation_daemon_phase28.py` n'importe que engine/daemon/state |
| Aucun import `futures_kraken_cli` | PASS | grep scripts Phase 28/29 |
| `--cache-only` default | PASS | pas de fetch réseau OHLC |
| `--observation-only` default True | PASS | décisions → jsonl uniquement |
| Aggregator Phase 29 | PASS | lecture fichiers locaux seulement |

**Verdict : aucun chemin live activé.**

## 2. Persistance état

| Check | Verdict |
|-------|---------|
| state.json présent (2 cibles) | PASS |
| decisions.jsonl append-only | PASS |
| shadow_comparison.jsonl append-only | PASS |
| equity_curve.csv append-only | PASS |
| Idempotence duplicate_candle | PASS (re-run once → skipped) |

## 3. Duplicate candle

- `is_duplicate_candle()` dans `overlay_observation_engine.run_observation_once()` compare `last_processed_timestamp` vs dernière bougie cache.
- Re-run `--mode once` sur état chaud → `skipped/duplicate_candle` sans double append shadow.
- **PASS**

## 4. Stale derivatives detection

- OHLC stale : `is_stale_data()` gap >3j.
- Derivatives : basis absent → `funding_only` + kill config `stale_data=True`.
- Erreurs loggées dans `errors.log` via `log_error()`.
- Aggregator compte `stale_data_count` depuis decisions + errors.
- **PASS** (mécanisme en place ; T0 sans stale signal)

## 5. STOP_OBSERVATION respecté

- Fichier absent au sanity check.
- `observation_stop_active()` court-circuite le daemon → `{"status": "stopped"}`.
- Aggregator expose `stop_observation_active`.
- **PASS**

## 6. Cohérence overlay decisions

- Shadow rows : `overlay_decision`, `overlay_reason`, `funding_z`, `basis_z` alignés decisions.jsonl.
- T0 : allow/neutral, basis_z≈1.43, pas de block incohérent.
- Kill `incoherent_blocks` évalue z-score <1.5 sans block extrême.
- **PASS**

## 7. Fichiers sensibles

```text
git diff HEAD -- src/execution.py src/risk.py src/futures_kraken_cli.py config.yaml web/
→ (empty)
```

**UNCHANGED — PASS**

## Risques résiduels

1. **state.json legacy fields** — champs asset/strategy obsolètes ; corriger au prochain cold-start si confusion opérationnelle.
2. **Parallèle daemon Phase 19** — anti-pattern documenté Phase 28.
3. **Suppression manuelle STOP_OBSERVATION** — relance sans revue humaine possible.

## Verdict red team

**PASS — continue_observation** (ops setup OK, pas de fix bloquant).
