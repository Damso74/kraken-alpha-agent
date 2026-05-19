# Protocoles agentiques Phase 13

**Hypothèse figée :** volume shock multi-actif (BTC, ETH, SOL si cache) — réplication `src/signals/volume_shock.py`, hold-out G4, provenance Phase 12.

## Protocole A — single-agent

**Workflow**

1. Lire manifest `reports/data_manifests_phase13/ohlcv_multi_asset_manifest.json`.  
2. Lancer (cache-only) :
   ```powershell
   python scripts/event_study_volume_shock.py --run-all-variants --days 365 `
     --ohlc-source cache --use-cache-only --enable-holdout --holdout-fraction 0.5 `
     --embargo-days 7 --assets BTC,ETH,SOL `
     --output-dir reports/research_runs_phase13 --protocol protocol_a
   ```
3. Rédiger verdict dans `reports/protocol_a_single_agent/`.  
4. Ne pas optimiser de seuils post-hoc.

**Livrables :** `SINGLE_AGENT_REPORT.md`, JSON sous `research_runs_phase13/`.

## Protocole B — builder + red team

**Workflow**

1. Builder : même run JSON que A (données identiques).  
2. Builder rédige `BUILDER_REPORT.md` (peut sur-estimer si BH sans placebos).  
3. Red team indépendant : `RED_TEAM_REPORT.md` — attaque placebos p=1, hold-out, partial assets.  
4. `FINAL_VERDICT.md` = min(builder, red team) — plus conservateur en cas de doute.

**Livrables :** `reports/protocol_b_builder_red_team/`.

## Protocole C — full committee

**Workflow**

1. Six rôles documentés (pas six runs réseau).  
2. Chaque rôle répond à sa checklist (data, méthode, coûts, repro, gate).  
3. PM agrège → `COMMITTEE_FINAL_VERDICT.md`.  
4. Scores dans `reports/agent_scores_phase13/protocol_c_scores.json`.

**Livrables :** `reports/protocol_c_full_committee/*.md`.

## Alignement inter-protocoles

| Dimension | Règle |
|-----------|--------|
| Variantes | `vol_z20_high`, `vol_z60_high`, `vol_z20_range_compression`, `vol_z20_low_abs_return` |
| Seuils z | ≥ 2,0 pré-enregistrés — **non modifiables** |
| Fenêtres | `post_3`, `post_7` (vol / drawdown) |
| Placebos | shift +30j, shuffle labels, bootstrap count |
| Hold-out | `--enable-holdout`, fraction 0,5 |
| Source OHLC | `cache` + `--use-cache-only` |

## Verdicts autorisés

`blocked`, `blocked_data`, `insufficient_events`, `weak evidence`, `kill`, `failed holdout`, `not replicated`, `candidate for further validation` — **pas** tradable / profitable / live-ready.
