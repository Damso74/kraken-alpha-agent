# AGENTS.md

## Learned User Preferences

- User delegates large multi-phase tasks to background subagents (Multitask Mode) and expects concise, high-level confirmations once each subagent completes.
- User often provides explicit numbered or lettered plans; follow them in order rather than improvising a different sequence.
- Existing pytest suite (currently 158 tests) must stay green after every change.
- Never log secrets and keep `.env` untracked; only `.env.example` is committed.
- User runs commands from PowerShell on Windows 11; activate the Python venv via `.\.venv\Scripts\Activate.ps1` before Python work.
- Local network blocks outbound TCP/22 by default; user switches to a mobile hotspot (or falls back to the Vultr web console) whenever SSH to the VPS is required.
- Safe-by-default live sequence (never bypass any step): `scripts/validate_live_xstocks.py` -> shadow run >=20 min -> `scripts/live_preflight.py --allow-live-env-check` -> manual confirmation -> `kraken order cancel-after 60` -> `scripts/run_agent_loop.py`.
- Friday end-of-day rule (CEST): 21:45 stop opening new BUY orders, 21:45-21:55 flatten open positions, 22:00 hard-stop the loop.
- Kraken trading keys and the Vultr API key were exposed in chat once; user accepts the risk pending post-hackathon rotation (rotate the Kraken WRITE key, regenerate the Vultr key, then re-restrict allowlists).

## Learned Workspace Facts

- Project root: `c:\Users\credo\Documents\Code_Informatique\Projets-en-cours\kraken-alpha-agent`, isolated local git repo (separate from ArcadeOps); GitHub remote `https://github.com/Damso74/kraken-alpha-agent.git` (branch `master`).
- Hackathon target: lablab "AI Agent Olympics", track "Kraken Trading Performance" (ranking on net PnL, audited via Kraken read-only key).
- Kraken CLI 0.3.2 is installed only inside WSL Ubuntu; the wrapper auto-detects the WSL transport from Windows (override with `KRAKEN_CLI_TRANSPORT`) and invokes commands via `wsl -- bash -lc "kraken ..."`. On the Linux VPS, `KRAKEN_CLI_TRANSPORT=auto` resolves to the native `kraken` binary in `$PATH`.
- xStocks pair format is the slash form `TICKERx/USD` (e.g. `AAPLx/USD`, `TSLAx/USD`). Read-only subcommands (`ticker`, `ohlc`, `orderbook`, `trades`) and `order buy/sell` accept `--asset-class tokenized_asset` and require it to resolve xStocks pairs.
- `kraken 0.3.2 paper buy/sell` does **NOT** expose `--asset-class` (the flag is rejected with `error: unexpected argument '--asset-class' found`). As a result the paper engine cannot route xStocks pairs and returns `EQuery:Unknown asset pair`. This is an upstream CLI limitation; do NOT inject the flag into `paper buy/sell`. The agent loop handles this transparently via `src/execution._simulate_paper_fill` (deterministic local simulation labelled `simulated`); `scripts/paper_smoke_test.py --place-test-order` detects the rejection and logs the fallback message `Kraken CLI paper engine may not support xStocks; falling back to local simulation.`.
- `kraken orderbook` and `kraken trades` use `--count`, not `--depth`.
- Paper account is already initialized (`kraken paper init --balance 10000 --currency USD --yes`); paper buy/sell remain gated behind explicit CLI flags.
- Default execution mode is `dry_run`; live trading must remain blocked by the triple opt-in (config flag + env var + CLI flag) and `shorting=false` is enforced in the ensemble and execution layers.
- `config.yaml` is hand-curated; active profile remains `aggressive_competition`, and a new `micro_live_100eur` profile (`max_total_exposure_usd=30`, `max_position_usd=10`) is available but not the default. All edits must preserve the triple opt-in and `shorting=false`.
- Stack overview: deterministic engine (features/regime/strategies/ensemble/risk), Kraken CLI wrapper with mock fallback, FastAPI dashboard, SQLite + JSONL audit logs, ranking script for the xStocks universe, plus a backtester (`src/backtest.py` + `scripts/backtest_xstocks.py`) labelled `backtest_local_estimate`.
- Vultr VPS provisioned for live runs: IP `140.82.12.75`, region `ewr`, plan `vhf-1c-2gb` (Ubuntu 24.04 LTS x64), SSH key `~/.ssh/kraken_vps_ed25519`, project deployed at `/root/kraken-alpha-agent`. The VPS `.env` carries only the WRITE Kraken key + `KRAKEN_CLI_TRANSPORT=auto`; live flags (`TRADING_MODE=live`, `LIVE_TRADING=true`, `ALLOW_LIVE_ORDERS=true`) are exported per-session and never persisted.
- Local working tree carries an unpushed live-readiness patch (`src/exit_rules.py`, `src/sessions.py`, `scripts/validate_live_xstocks.py`, `scripts/live_preflight.py`, `scripts/run_vps_micro_live.sh`, `scripts/run_vps_shadow.sh`, `docs/VPS_RUNBOOK.md`, related tests under `tests/`). `master` on GitHub is therefore behind the local working tree until an explicit commit + push.
- Local working tree ALSO carries an unpushed **Kraken Futures Perpetual xStocks pivot** layered on top of the live-readiness patch (`src/futures_kraken_cli.py`, futures branch in `src/execution.py`, `max_leverage`/`max_funding_rate` gates in `src/risk.py`, `FuturesConfig` + `ExecutionConfig.engine` in `src/config.py`, `mark_price`/`funding_rate_pct_per_hour` on `Features`, `scripts/validate_live_xstocks_perps.py`, futures checks in `scripts/live_preflight.py`, `futures:` block in both YAML configs, `KRAKEN_FUTURES_API_KEY`/`_SECRET` in `.env.example`, plus the test suite `tests/test_futures_*`). Test count moved from 158 → 207 green.

## Conscious overrides (recorded, not violated)

- **Futures + leverage override (2026-05-15).** EU/PEDSL-CY accounts cannot trade the spot xStocks orderbook on Kraken Spot, so the user explicitly opted into routing the live engine through **Kraken Futures Perpetual xStocks** instead. The override is conditional on intransigeant safeguards:
  - `src.risk.HARDCODED_MAX_LEVERAGE = 1.0`; any caller asking for >1x is refused by the risk gate AND raises in `src.futures_kraken_cli._build_order_args` (defence-in-depth). Effective leverage = 1.0 = spot equivalent, no margin call surface.
  - SELL is exit-only on the futures engine: `execution._execute_futures` refuses any SELL without an open long and forces `--reduce-only` on the wire.
  - `flatten_before_close_exit` still fires 15 min before US_CORE close → no overnight funding accrual.
  - Funding-rate gate: BUY refused when `features.funding_rate_pct_per_hour > futures.max_funding_rate_pct_per_hour` (default 0.5%/h).
  - Triple opt-in (`TRADING_MODE=live` + `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true`) is unchanged and remains mandatory; never persisted to `.env`.
  - The `micro_live_100eur` profile is the only profile that pivots to `execution.engine: futures`; the active default (`aggressive_competition`) stays on `engine: spot` so existing tests and dry-runs are not perturbed.
  - The agent never calls `kraken futures transfer` / `wallet-transfer`. The user's Futures API key SHOULD have withdrawal disabled.
