# Phase 28 — ETH 4h overlay paper observation

**Branche :** `phase28/eth4h-overlay-paper-observation`  
**Objectif :** Forward paper observation des 2 overlays utiles Phase 27 (funding+basis).

## Cibles

| Strategy | Variant | Overlay | Verdict Phase 27 |
|----------|---------|---------|------------------|
| trend_following | baseline | funding_basis | useful_overlay |
| ema_crossover | baseline | funding_basis | useful_overlay |

## Composants

| Module | Rôle |
|--------|------|
| `scripts/run_overlay_observation_daemon_phase28.py` | Daemon once/loop, observation-only default |
| `src/bot/overlay_observation_engine.py` | Moteur cache-only, paper sim + shadow |
| `src/bot/overlay_shadow_compare.py` | Standalone vs overlay vs B&H/cash |
| `src/bot/overlay_observation_kill.py` | Kill criteria + STOP_OBSERVATION |
| `scripts/generate_overlay_observation_report_phase28.py` | Rapports daily/weekly |

## État persisté

```
reports/paper_observation_phase28/
├── trend_following_baseline/
│   ├── state.json
│   ├── decisions.jsonl
│   ├── shadow_comparison.jsonl
│   ├── equity_curve.csv
│   └── errors.log
├── ema_crossover_baseline/
│   └── (idem)
├── KILL_CRITERIA.md
└── STOP_OBSERVATION          # créé si kill
```

## QA demo (cache réel)

```
trend_following baseline: equity=1112.09, trades=114, overlay=allow/neutral
ema_crossover baseline:   equity=965.88,  trades=100, overlay=allow/neutral
funding_z=0.0, basis_z=1.43 @ ts=1779264000
```

## Tests

862 tests verts (+9 Phase 28). Aucun réseau, aucun live side effect.

## Verdict

Observation-only **GO**. Micro-live **NO-GO** (`MICRO_LIVE_GO_NO_GO_PHASE28.md`).
