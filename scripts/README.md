# Scripts — index

**Total :** ~77 Python + 6 shell + 2 PowerShell (audit 2026-05-21)

Les modules `_phase*_common.py` et `_event_study_common.py` sont des bibliothèques internes importées par les runners de phase — ne pas supprimer sans grep d’imports.

---

## Agent loop & sécurité

| Script | Usage |
|--------|-------|
| `dry_run_once.py` | Un cycle agent complet, sans ordre |
| `run_agent_loop.py` | Boucle continue (Ctrl+C) |
| `check_kraken_cli.py` | Probe CLI + mock fallback |
| `probe_xstocks.py` | Read-only xStocks (4 appels × N symboles) |
| `paper_smoke_test.py` | Statut paper ; `--init`, `--place-test-order` |
| `rank_xstocks.py` | Classement opportunités → `data/xstocks_rank_*` |
| `analyze_paper_run.py` | Rapport Markdown session paper |
| `validate_live_xstocks.py` | Validation wire spot (clés requises) |
| `validate_live_xstocks_perps.py` | Validation perps futures |
| `live_preflight.py` | Preflight triple opt-in |
| `export_audit_bundle.py` | Bundle audit secrets redacted |

---

## Observation forward (Phase 28–30)

| Script | Usage |
|--------|-------|
| `run_overlay_observation_daemon_phase28.py` | Daemon / `--mode once` |
| `ops_run_observation_once_phase30.ps1` | Ops Windows : refresh + once + reports |
| `ops_run_observation_once_phase30.sh` | Ops Linux/VPS (cron 4 h) |
| `install_observation_cron_phase30.sh` | Installer cron VPS |
| `uninstall_observation_cron_phase30.sh` | Retirer cron |
| `aggregate_observation_metrics_phase29.py` | Agrégation métriques |
| `generate_observation_dashboard_phase30.py` | Cockpit HTML statique |
| `generate_observation_alerts_phase30.py` | Alertes |
| `generate_observation_ops_digest_phase30.py` | Digest ops |
| `check_observation_health_phase30.py` | Healthcheck |
| `migrate_observation_state_phase30_1.py` | Migration état |

---

## Walk-forward & tournaments (research)

| Phase | Scripts principaux |
|-------|-------------------|
| 14–16 | `run_strategy_tournament.py`, `run_walkforward_tournament.py`, `build_intraday_cache.py` |
| 18 | `run_regime_router_tournament.py` |
| 22 | `benchmark_regime_router_phase22.py`, `run_fee_sensitivity_phase22.py`, `run_risk_sensitivity_phase22.py`, `generate_phase22_reports.py` |
| 23 | `run_lowfreq_candidate_factory_phase23.py`, `run_lowfreq_walkforward_phase23.py`, `run_regime_overlay_phase23.py` |
| 24 | `audit_data_backbone_phase24.py`, `run_lowfreq_walkforward_sensitivity_phase24.py` |
| 25 | `run_candidate_autopsy_phase25.py` |
| 26 | `build_derivatives_cache_phase26.py`, `run_crowding_overlay_tournament_phase26.py` |
| 27 | `build_basis_cache_phase27.py`, `run_basis_overlay_tournament_phase27.py`, `run_eth4h_overlay_autopsy_phase27.py` |

Communs : `_phase22_common.py`, `_phase23_common.py`, `_phase26_common.py`, `_phase27_common.py`

---

## Event studies & signaux

| Script | Signal / source |
|--------|-----------------|
| `event_study_calendar.py` | Sessions, week-end |
| `event_study_eth_gas.py` | Gas ETH (Etherscan) |
| `event_study_exchange_status.py` | Status pages |
| `event_study_stablecoins.py` | Stablecoin supply |
| `event_study_volume_shock.py` | Volume shock |
| `event_study_wikipedia.py` | Wiki attention |
| `event_study_deribit_expiry.py` | Options expiry |
| `demo_event_study.py` | Démo |

Commun : `_event_study_common.py`

---

## Soumission hackathon

| Script | Output |
|--------|--------|
| `backtest_xstocks.py` | Backtest xStocks |
| `export_submission_backtest.py` | JSON pour `web/public/data/` |
| `walk_forward_xstocks.py` | Walk-forward xStocks |
| `export_shadow_session_for_submission.py` | Export session shadow |

---

## Outils opérateur (non importés par tests)

| Script | Usage |
|--------|-------|
| `_inspect_wf_crypto.py` | Inspecte `data/walk_forward_crypto_results.json` |
| `_inspect_wf_results.py` | CLI résumé JSON walk-forward |
| `audit_ohlcv_caches.py` | Audit caches OHLCV |
| `optuna_crypto_search.py` | Hyperparam search (optuna) |

---

## Live / shadow (opt-in explicite)

| Script | Note |
|--------|------|
| `monitor_shadow_session.py` | Monitoring shadow |
| `monitor_live_session.py` | Monitoring live futures |
| `live_crypto_with_killswitch.py` | Live crypto + killswitch |
| `run_vps_shadow*.sh`, `run_vps_micro_live.sh` | VPS runners |

**Ne pas exécuter live sans séquence `AGENTS.md`.**

---

## Conventions

- Suffixe `_phaseNN` = batch recherche ou ops lié à la phase N
- Préfixe `_` = module interne ou outil opérateur
- PowerShell ops : `$ErrorActionPreference = "Stop"` ; logs UTC dans `reports/paper_observation_phase28/ops_logs/`
