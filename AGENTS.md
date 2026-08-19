# AGENTS.md

## Learned User Preferences

- User prefers responses in French.
- User delegates large multi-phase tasks to background subagents (Multitask Mode) and expects concise, high-level confirmations once each subagent completes.
- User often provides explicit numbered or lettered plans; follow them in order rather than improvising a different sequence.
- After the observation cockpit is ready (Phase 30 ops), stop product/strategy dev; only exploitation code (cron, dashboard, alerts, state cleanup) until forward observation completes.
- Keep `master` frozen until hackathon payment/validation; do not merge feature branches to `master`; pushing feature branches and separate private backup remotes are OK.
- Existing pytest suite must stay green after every change.
- Never log secrets and keep `.env` untracked; only `.env.example` is committed.
- User runs commands from PowerShell on Windows 11; activate the Python venv via `.\.venv\Scripts\Activate.ps1` before Python work; `&&` does NOT chain in PowerShell — use `;`; CRLF breaks VPS bash/python — strip on remote with `tr -d '\r'`; local network blocks TCP/22 — use mobile hotspot or Vultr web console for SSH.
- Safe-by-default live sequence (never bypass): `scripts/validate_live_xstocks.py` -> shadow >=20 min -> `scripts/live_preflight.py --allow-live-env-check` -> manual confirmation -> `kraken order cancel-after 60` -> `scripts/run_agent_loop.py`. Friday EOD (CEST): 21:45 stop new BUYs, 21:45-21:55 flatten, 22:00 hard-stop. Micro-live NO-GO until 2–4 weeks clean forward paper observation (J+7/J+14/J+28 reviews).
- Kraken trading keys and the Vultr API key were exposed in chat once; user accepts the risk pending post-hackathon rotation (rotate the Kraken WRITE key, regenerate the Vultr key, then re-restrict allowlists).
- Submission page honesty rule (recurring): the `web/` dashboard must display ONLY real backtest numbers from `web/public/data/backtest_xstocks_*.json`; never label static data as "live" or "real-time" (badge "READY FOR DEMO" and "Agent Online" are OK, "Live trading" / "Live xStocks fills" are NOT); the "What Blocked xStocks" section must quote verbatim API error strings (`EGeneral:Permission denied`, `wouldNotReducePosition`) as wire-level evidence; if the backtest produces a negative PnL, show the negative number honestly.
- Anti-curve-fit policy when the user asks to "improve" backtest numbers: always prefer walk-forward parameter optimization with a strict out-of-sample filter (`test_pnl_usd >= 0` AND `test_win_rate >= 50%` AND `trades_count >= 30`) over naive grid tuning; if zero configs survive the OOS filter, keep the current config and document the honest negative result in `docs/METHODOLOGY.md` rather than chase metrics; the 30d recent snapshot must always sit in the TEST half of the split, never in train.

## Learned Workspace Facts

- Project root: `c:\Users\credo\Documents\Code_Informatique\Projets-en-cours\kraken-alpha-agent`, isolated local git repo; GitHub remote `https://github.com/Damso74/kraken-alpha-agent.git` (branch `master`). Hackathon: lablab "AI Agent Olympics", track "Kraken Trading Performance" — structurally inaccessible to PEDSL-CY accounts on live xStocks PnL; non-EU/EEA Kraken entity required.
- Kraken CLI 0.3.2 runs in WSL Ubuntu from Windows (`KRAKEN_CLI_TRANSPORT` override); native on Linux VPS (`auto` → `$PATH` binary).
- xStocks pairs use slash form `TICKERx/USD`; read commands need `--asset-class tokenized_asset`. `kraken paper buy/sell` rejects xStocks (no `--asset-class`); agent loop simulates via `src/execution._simulate_paper_fill`.
- **PEDSL-CY (Cyprus EU) blocks all xStocks API trading**: spot returns `EGeneral:Permission denied`; futures perps return `wouldNotReducePosition` on BUY — no live xStocks path until account migration.
- Kraken separates Spot/Futures keys; Futures write key = `Trades`+`Positions` only. `data/jury_readonly_credentials.md` (gitignored) holds both read-only keys. Ten xStocks perps on PEDSL-CY (`PF_*XUSD`); mapping in `src/futures_kraken_cli.py`.
- **Futures CLI**: literal `order` required (`kraken futures order buy/sell`); no `--validate`; paper uses `kraken futures paper *`. Size to 2 decimals; `run_futures_cli` whitelists success statuses only (`placed`, `filled`, etc.) — Kraken returns HTTP 200 on rejections.
- `src/risk.evaluate_risk(action="SELL", is_exit_action=True, ...)` MUST bypass exposure/position caps (exit-only; does not relax `shorting=false`).
- Default mode `dry_run`; live needs triple opt-in. Active profile `aggressive_competition`; `micro_live_100eur` pivots to futures engine. VPS: Ubuntu 24.04 at `/root/kraken-alpha-agent`, region `ewr`; live flags per-session only.
- `web/` is Next.js submission dashboard (static JSON from `web/public/data/` only, Vercel auto-deploy on `master` push). Core trading files off-limits to UI subagents. Submission scripts: `backtest_xstocks.py`, `export_submission_backtest.py`, `walk_forward_xstocks.py`, `export_audit_bundle.py`. Docs in `docs/` (SUBMISSION, METHODOLOGY, JURY_ACCESS, etc.).
- Bot research pipeline (`src/bot/`, phases 16–30 on feature branches, not merged to `master`): Binance public caches gitignored in `data/collector_cache/` (BTC/ETH/SOL 1d/4h/1h + derivatives funding/basis). Exhaustive backtests: **0 paper_candidate**; price-only OHLCV exhausted after Phase 25 autopsy (no raw edge at zero fees; risk manager minor blocker; **4h best TF**; regime router = overlay not alpha). Derivatives funding+basis useful as risk overlay only; **ETH 4h funding+basis overlay** on `trend_following`/`ema_crossover` baselines is the active research track.
- Forward paper observation ops: `scripts/ops_run_observation_once_phase30.sh` / `.ps1` refreshes public caches then runs `run_overlay_observation_daemon_phase28.py --mode once`; state under `reports/paper_observation_phase28/`; static cockpit at `reports/paper_observation_phase28/dashboard.html` (NOT `web/`); metrics in `reports/phase29_observation_metrics/summary.json`; VPS **cron every 4h** preferred over infinite loop; `STOP_OBSERVATION` flag halts runs; `--cache-only` without refresh observes stale cache only.

## Conscious overrides (recorded, not violated)

- **Futures + leverage override (2026-05-15).** EU/PEDSL-CY accounts cannot trade the spot xStocks orderbook on Kraken Spot, so the user explicitly opted into routing the live engine through **Kraken Futures Perpetual xStocks** instead. The override is conditional on intransigeant safeguards:
  - `src.risk.HARDCODED_MAX_LEVERAGE = 1.0`; any caller asking for >1x is refused by the risk gate AND raises in `src.futures_kraken_cli._build_order_args` (defence-in-depth). Effective leverage = 1.0 = spot equivalent, no margin call surface.
  - SELL is exit-only on the futures engine: `execution._execute_futures` refuses any SELL without an open long and forces `--reduce-only` on the wire.
  - `flatten_before_close_exit` still fires 15 min before US_CORE close → no overnight funding accrual.
  - Funding-rate gate: BUY refused when `features.funding_rate_pct_per_hour > futures.max_funding_rate_pct_per_hour` (default 0.5%/h).
  - Triple opt-in (`TRADING_MODE=live` + `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true`) is unchanged and remains mandatory; never persisted to `.env`.
  - The `micro_live_100eur` profile is the only profile that pivots to `execution.engine: futures`; the active default (`aggressive_competition`) stays on `engine: spot` so existing tests and dry-runs are not perturbed.
  - The agent never calls `kraken futures transfer` / `wallet-transfer`. The Futures write API key MUST be created with `Trades` + `Positions` only and `Withdrawal` / `Transfer` / `Funding` disabled; the existing Spot key cannot be reused for futures.
  - Because `kraken futures order` has no `--validate` flag, there is no mainnet dry-run for futures: the first live futures order is necessarily a real wire-level order and must be sized minimal (1x, isolated, micro nominal). All pre-live validation runs through `kraken futures paper *` (which itself requires `kraken futures paper init` to have been run on the host once).

## Repository audit (2026-08-19)

- Tests : **1058** collectés (`python -m pytest -q`), 126 fichiers, ~3 min
- CI : `.github/workflows/ci.yml` — ruff + shellcheck + pytest + `git diff --exit-code`.
  **Elle n'avait jamais exécuté un seul test avant le 2026-08-19** (`ruff` absent de
  `requirements.txt` → `exit 127` au step lint). Voir ADR-013.
- Verdict de la recherche : **`reports/PHASE31_FINAL_VERDICT.md`** — 0 signal tradable,
  observation forward archivée. Lire ce document avant toute reprise.
- Rapports d'audit antérieurs : `reports/PHASE1_AUDIT_REPORT.md`,
  `reports/REPOSITORY_AUDIT_FINAL.md` (le score « 72/100 → 78/100 » qui figurait ici
  n'était étayé par aucune mesure : ni couverture, ni CI verte)
- Scripts index : `scripts/README.md`
