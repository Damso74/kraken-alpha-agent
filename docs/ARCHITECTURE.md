# Architecture — kraken-alpha-agent

Document basé sur l’état réel du dépôt (branche `phase30/observation-ops-ux`, audit 2026-05-21).

---

## Vue d’ensemble

Le projet combine trois surfaces :

1. **Agent compétition xStocks** — pipeline déterministe Kraken CLI (`src/main.py` → execution/risk).
2. **Pipeline recherche quantitatif** — backtests, walk-forward, overlays (`src/bot/`, `src/research/`, `scripts/run_*_phase*.py`).
3. **Observation forward** — paper overlay ETH 4h en cron VPS (Phase 28–30).

Deux dashboards coexistent :

- `src/dashboard/` — FastAPI local (terminal trading, audit loop).
- `web/` — Next.js statique pour soumission hackathon (JSON embarqués uniquement).

---

Entrypoints distincts (ne pas confondre) :

| Surface | Entrypoint script | Orchestrateur | Risk / portfolio |
|---------|-------------------|---------------|------------------|
| Agent compétition | `scripts/run_agent_loop.py`, `dry_run_once.py` | `src/main.py` | `src/risk.py`, `src/portfolio.py` |
| Recherche / backtest | `scripts/run_*_phase*.py` | runners phase | `src/bot/risk_manager.py`, `src/bot/portfolio.py` |
| Observation forward | `scripts/ops_run_observation_once_phase30.*` | `run_overlay_observation_daemon_phase28.py` | overlay bot (paper only) |

---

## Pipeline agent (live / paper / dry_run)

```
kraken_cli / futures_kraken_cli
    → market_data → features → regime
    → strategies (momentum, breakout, mean_reversion) → ensemble
    → actionability → risk → execution → storage / portfolio / pnl
```

| Module | Fichier | Rôle |
|--------|---------|------|
| Orchestrateur | `src/main.py` | `run_one_cycle`, session guard, exit rules |
| Config | `src/config.py` | `.env` + `config.yaml`, profils deep-merge |
| CLI | `src/kraken_cli.py` | Subprocess + mock ; transport auto/wsl/mock |
| Futures | `src/futures_kraken_cli.py` | Perps xStocks (profil `micro_live_100eur`) |
| Risk | `src/risk.py` | Gate unique ; triple opt-in live |
| Execution | `src/execution.py` | dry_run / paper / spot / futures |
| Portfolio live | `src/portfolio.py` | Positions SQLite, source `local_estimate` |

Entrypoints scripts :

- `scripts/dry_run_once.py` — un cycle
- `scripts/run_agent_loop.py` — boucle continue
- `scripts/paper_smoke_test.py` — probe paper account

---

## Pipeline recherche (phases 16–30)

| Couche | Emplacement | Rôle |
|--------|-------------|------|
| Collectors | `src/data/collectors/` | Binance public, DeFiLlama, Etherscan, Wikimedia, status pages |
| Signaux | `src/signals/` | Builders d’événements pour event studies |
| Event study | `src/research/event_study.py` | Évaluation statistique des signaux |
| Bot core | `src/bot/` | Paper engine, regime router, overlays funding/basis |
| Strategies zoo | `src/strategies/` | Presets backtest (EMA, Donchian, grid, …) |
| Scripts phase | `scripts/run_*_phase*.py` | Tournaments, walk-forward, autopsies |

**Portfolio paper :** `src/bot/portfolio.py` (`PaperPortfolio`) — utilisé par backtests et overlays, **distinct** de `src/portfolio.py`. Voir aussi `docs/PAPER_TRADING_BOT.md`.

**Risk backtest :** `src/bot/risk_manager.py` — caps exposure pour simulations, **distinct** de `src/risk.py`.

Caches publics (gitignored) : `data/collector_cache/`.

---

## Observation forward (Phase 28–30)

| Composant | Chemin |
|-----------|--------|
| Daemon overlay | `scripts/run_overlay_observation_daemon_phase28.py` |
| Ops once (cron) | `scripts/ops_run_observation_once_phase30.ps1` / `.sh` |
| État | `reports/paper_observation_phase28/` |
| Cockpit statique | `reports/paper_observation_phase28/dashboard.html` |
| Métriques | `reports/phase29_observation_metrics/summary.json` |
| Arrêt | flag `reports/paper_observation_phase28/STOP_OBSERVATION` |

Le cron VPS (toutes les 4 h) préfère `--mode once` à une boucle infinie.

---

## Modes et profils

| Mode | Comportement |
|------|--------------|
| `dry_run` | Défaut — log decisions, pas d’ordre |
| `paper` | CLI paper ou simulation locale xStocks |
| `live` | Triple opt-in obligatoire |

Profils dans `config.yaml` : `balanced`, `aggressive_competition`, `conservative_debug`, `micro_live_100eur` (futures). Override env : `KRAKEN_ALPHA_PROFILE`.

---

## Transport Kraken CLI

| `KRAKEN_CLI_TRANSPORT` | Usage |
|------------------------|-------|
| `auto` | Windows → WSL → mock |
| `wsl` | Force WSL |
| `mock` | Tests / CI |

---

## Fichiers protégés (ne pas modifier sans justification forte)

- `config.yaml`
- `src/execution.py`, `src/risk.py`, `src/futures_kraken_cli.py`
- `web/` (règle honnêteté soumission)

---

## Références

- `README.md` — quickstart jury
- `docs/QUALITY.md` — tests, CI, secrets
- `docs/DECISIONS.md` — décisions structurantes
- `docs/PAPER_OBSERVATION_DESIGN.md` — design observation
- `AGENTS.md` — préférences agent Cursor
