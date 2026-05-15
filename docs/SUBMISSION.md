# Kraken Alpha Agent — Submission packet

> Companion document for the **AI Agent Olympics — Kraken Trading
> Performance** submission. Everything here is summarised from the codebase
> as it exists at the freeze commit; consult the linked files for source
> of truth.

## Title

**Kraken Alpha Agent** (public alias: *Kraken Sentinel*).

## Short description

> Autonomous xStocks trading agent built on Kraken CLI, ranking tokenized
> equities by momentum, liquidity and spread, then executing through a
> safety-gated dry-run / paper / live pipeline with auditable PnL logs.

## Long description

Kraken Alpha Agent is an **autonomous**, **transparent**, **auditable** and
**safe-by-default** trading agent for tokenized equities (xStocks) on the
Kraken venue. It runs a deterministic decision pipeline on top of the
Kraken CLI:

- Polls real xStocks market data via `kraken ticker / ohlc / orderbook /
  trades --asset-class tokenized_asset`.
- Engineers a small feature set per symbol (multi-horizon returns, realised
  volatility, spread bps, distance from 1h high/low, volume).
- Classifies the market regime (rule-based logistic over short/long returns
  and realised vol).
- Runs three independent strategies (momentum, breakout, mean reversion)
  and blends them in a liquidity-aware ensemble.
- Applies an **actionability layer** that downgrades unsafe intents to
  `HOLD` *before* the risk manager: BUY threshold, negative-opportunity
  veto, SELL exit-only, no-short default (env + YAML must both opt in),
  liquidity-based size dampener.
- Routes the approved action through the **risk manager** (allowlist,
  spread/regime guards, confidence floor, drawdown / exposure / cooldown
  caps, hourly trade rate limiter, **live triple opt-in**).
- Executes via dry-run (no order leaves the process), paper (Kraken paper
  CLI behind a 30-second init guard), or live (requires
  `TRADING_MODE=live` + `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true`,
  all simultaneously).
- Persists every decision, every order, every PnL snapshot and every error
  to **SQLite** + **JSONL** for full auditability; a FastAPI dashboard
  surfaces all of it with an Actionability panel and a `/ranking`,
  `/actionability`, `/pnl` and `/health` JSON API.
- Optional Featherless-hosted LLM explainer (OpenAI-compatible) attaches a
  short rationale to each decision when an API key is present; the explainer
  is purely advisory and never affects sizing or risk.

## Tags

`Kraken CLI`, `xStocks`, `Trading Agent`, `Autonomous Agent`, `Python`,
`FastAPI`, `SQLite`, `Risk Management`, `PnL Tracking`, `AI Agent Olympics`.

## Demo commands (copy / paste)

```powershell
# Tests
pytest

# Real xStocks ranking via Kraken CLI (WSL ok)
python scripts/rank_xstocks.py --top 8

# One full agent cycle, no orders placed
python scripts/dry_run_once.py

# Paper account health check (read-only by default)
python scripts/paper_smoke_test.py

# Continuous paper loop (requires manual `kraken paper init` first)
$env:TRADING_MODE = "paper"
python scripts/run_agent_loop.py

# Post-mortem report on a paper / dry-run session
python scripts/analyze_paper_run.py --since 24

# Audit bundle for the submission package
python scripts/export_audit_bundle.py

# Dashboard
uvicorn src.dashboard.app:app --reload
```

## Live execution — Perpetual Futures pivot

> **Context.** EU / PEDSL-CY accounts (the user's jurisdiction) cannot trade
> the spot xStocks orderbook on Kraken Spot at the time of submission.
> Hackathon ranking is computed from live PnL, so the project pivoted the
> live execution path to **Kraken Futures Perpetual xStocks**, which the
> same jurisdiction is authorised to trade. The override of the original
> "no futures, no leverage" rule is **explicit and conscious** and is
> paired with intransigeant safeguards centralised in the risk gate.

### Why this is still "spot-equivalent"

| Concern (futures vs spot) | Mitigation in this agent |
|---|---|
| Margin call surface | `risk.HARDCODED_MAX_LEVERAGE = 1.0` — leverage > 1x is **refused** by `evaluate_risk` regardless of source (config, env, caller override). Wrapper `futures_kraken_cli._build_order_args` also raises if asked for >1x. Effective leverage = 1.0 = spot equivalent. |
| Funding rate drag | `risk.evaluate_risk` blocks BUY when `features.funding_rate_pct_per_hour > futures.max_funding_rate_pct_per_hour` (default 0.5%/h). Threshold is per-symbol because Kraken publishes 24 funding periods/day (= hourly funding for the xStocks Perps). |
| Overnight risk | The existing `flatten_before_close_exit` rule fires 15 minutes before US_CORE close (16:00 ET = 20:00 UTC during DST). No position survives the close → no overnight funding accrual. Friday end-of-day rule (21:45 CEST stop new BUYs, flatten before 21:55, hard stop 22:00) is unchanged. |
| Short opening | SELL is exit-only on the futures engine: `execution._execute_futures` refuses any SELL without an open long and forces `--reduce-only` on the wire. |
| Withdrawals | The agent never calls `kraken futures transfer` or `wallet-transfer`. The user's Futures API key SHOULD have the withdrawal permission disabled. |

### Architecture

```
config.execution.engine
        |
        +---- "spot"  (default) -> src/kraken_cli.place_order      (legacy spot xStocks path)
        |
        +---- "futures"          -> src/futures_kraken_cli.place_*  (Kraken Futures Perpetual venue)
```

- **`config.execution.engine`** — `spot` for the active competition profile
  (`aggressive_competition`); `futures` for `micro_live_100eur`.
- **`config.futures.max_leverage`** — read by the risk gate; capped at
  `HARDCODED_MAX_LEVERAGE = 1.0`.
- **`config.futures.max_funding_rate_pct_per_hour`** — funding cap
  (default 0.5%/h).
- **`src/futures_kraken_cli.py`** — single chokepoint for every `kraken
  futures …` invocation. Owns the spot↔futures symbol mapping.
- **`src/risk.py`** — exposes two new gates (`max_leverage`,
  `max_funding_rate`) and the public `HARDCODED_MAX_LEVERAGE` constant.
- **`scripts/validate_live_xstocks_perps.py`** — validate-only check via
  the futures **paper** engine because `kraken futures order buy` does
  not expose `--validate` on `kraken 0.3.2`.

### xStocks spot ↔ Futures mapping (discovered 2026-05-15 via `kraken futures instruments -o json`)

| Spot symbol  | Kraken Futures symbol | Type              | Tick   | Funding (periods/day) |
|--------------|-----------------------|-------------------|--------|----------------------|
| AAPLx/USD    | PF_AAPLXUSD           | flexible_futures  | 0.01   | 24                   |
| NVDAx/USD    | PF_NVDAXUSD           | flexible_futures  | 0.01   | 24                   |
| TSLAx/USD    | PF_TSLAXUSD           | flexible_futures  | 0.01   | 24                   |
| GOOGLx/USD   | PF_GOOGLXUSD          | flexible_futures  | 0.01   | 24                   |
| SPYx/USD     | PF_SPYXUSD            | flexible_futures  | 0.10   | 24                   |
| QQQx/USD     | PF_QQQXUSD            | flexible_futures  | 0.10   | 24                   |
| MSTRx/USD    | PF_MSTRXUSD           | flexible_futures  | 0.01   | 24                   |
| CRCLx/USD    | PF_CRCLXUSD           | flexible_futures  | 0.01   | 24                   |
| HOODx/USD    | PF_HOODXUSD           | flexible_futures  | 0.01   | 24                   |
| GLDx/USD     | PF_GLDXUSD            | flexible_futures  | 0.10   | 24                   |

MSFTx, AMZNx and METAx are spot-only on Kraken and have **no** futures
counterpart — the futures engine blocks orders on those symbols with a
clean `no futures listing` error.

### Validate-only on futures

`kraken futures order buy <SYMBOL> <SIZE> --type market` has **no
`--validate` flag** on `kraken 0.3.2` (confirmed 2026-05-15). The validate
fallback used by `scripts/validate_live_xstocks_perps.py` is therefore
`kraken futures paper buy <SYMBOL> <SIZE> --type market --leverage 1
--yes`. The paper engine is auth-gated, uses real market data and never
touches mainnet collateral, so a successful paper fill is the closest
thing to a structural sanity check for the live order path.

### Triple opt-in unchanged

The futures pivot does **not** relax any safeguard. `TRADING_MODE=live`,
`LIVE_TRADING=true`, `ALLOW_LIVE_ORDERS=true` must all be set
simultaneously, and the live preflight (`scripts/live_preflight.py`)
additionally checks `futures_keys_present`, `futures_engine_active`,
`max_leverage_eq_1`, `funding_rate_threshold_set` and
`validate_perps_latest_has_ok_symbol` before authorising the flip.

## Track positioning

- **xStocks is the primary target** of this submission (AI Agent Olympics —
  Kraken Trading Performance). The deterministic engine, ranking, and
  audit log all assume `tokenized_asset` first; crypto pairs are NOT the
  primary track and are not configured in the active universe.
- **Kraken CLI paper engine xStocks limitation**: `paper buy/sell` rejects
  `--asset-class tokenized_asset` (see AGENTS.md). The execution layer
  detects this and falls back to a deterministic local simulation so
  paper-mode runs never crash on xStocks.
- **Live execution only after validate-only OK.**
  `scripts/validate_live_xstocks.py` is the gatekeeper: it never sends
  a real order (it ONLY calls `kraken order ... --validate`) and writes
  `data/validate_live_xstocks_latest.json`. `scripts/live_preflight.py`
  refuses to pass if that file is missing or empty. Live execution
  additionally requires the triple opt-in (see below).
- **Micro-live profile (`micro_live_100eur`)** caps exposure at
  **30 USD total** (`max_total_exposure_usd: 30`) and **10 USD per
  position** (`max_position_notional_usd: 10`). The profile is not
  active by default — `KRAKEN_ALPHA_PROFILE=micro_live_100eur` must be
  set explicitly. Shorting stays disabled regardless.
- **Every decision is logged and auditable.** SQLite + JSONL + the
  audit-bundle exporter remain the single source of truth.

## Safety notes

- **Triple opt-in for live orders.** `TRADING_MODE=live`, `LIVE_TRADING=true`
  and `ALLOW_LIVE_ORDERS=true` must all be set. The risk manager re-validates
  this at every cycle and `tests/test_risk.py` enumerates every partial
  combination of the three flags to prove the order is blocked.
- **SELL is exit-only by default.** The actionability layer refuses any SELL
  that would open a short position.
- **No shorting unless explicitly opted-in twice.** Shorts require both
  `SHORTING_ENABLED=true` in the env **and** `trading.shorting_enabled: true`
  in `config.yaml` (the two flags are kept independent on purpose).
- **Paper-init guard.** The execution layer caches `kraken paper status` for
  30 s; paper orders are refused with status `blocked_paper_not_initialized`
  whenever the paper account has not been initialised.
- **Secret masking.** `src/logger.py` masks API keys/secrets through both
  regex patterns and a comparison against current env values; tests assert
  this.
- **Read-only API key recommended** for the Kraken audit. The submission
  never asks for withdrawal permission and never executes live orders during
  the build.

## Kraken CLI validation summary

- CLI version: **`kraken 0.3.2`** (validated 2026-05-14, see
  [`CLI_VALIDATION.md`](../CLI_VALIDATION.md)).
- Transports supported by `src/kraken_cli.py`: `auto`, `windows`, `wsl`,
  `mock`. Auto-detection prefers native Windows binary, falls back to
  `wsl -- bash -lc "kraken …"`, then deterministic mocks.
- xStocks pair format: `TICKERx/USD` (slash form) with mandatory
  `--asset-class tokenized_asset`.
- Read-only calls exercised against the real CLI:
  - `kraken status`, `version`, `health`
  - `kraken ticker / ohlc / orderbook / trades / asset / pair`
  - `kraken paper status / balance / orders / history`
- **52 / 52 read-only calls succeeded; 0 orders placed** during validation.
- `kraken order buy/sell --validate` is wrapped by `validate_live_order`
  but only ever called behind the triple opt-in.

## PnL & audit explanation

The agent emits three PnL sources, clearly labelled in
`PnLSnapshot.source`:

| Source            | Provenance                                                                                  |
|-------------------|---------------------------------------------------------------------------------------------|
| `local_estimate`  | Computed in `src/pnl.py` from the local position book — for `dry_run` / mock fallback.      |
| `paper`           | Reflects Kraken's paper accounting when the paper account is initialised.                    |
| `live`            | Read straight from Kraken via the read-only API key during the audited race window.          |

SQLite schema (`data/agent.sqlite`, six tables managed by `src/storage.py`):

| Table          | What it captures                                                                |
|----------------|---------------------------------------------------------------------------------|
| `decisions`    | Every Decision record (full JSON payload incl. votes + risk + actionability).   |
| `orders`       | Every ExecutionResult, regardless of mode (dry / paper / live / blocked).        |
| `positions`    | Latest known position per symbol (mirrors paper / live snapshot).               |
| `pnl_snapshots`| Periodic PnL snapshots tagged by source.                                        |
| `errors`       | Structured error records with `where_label`, message and stack hash.            |
| `cycles`       | One row per `run_one_cycle` invocation with timings and symbols seen.           |

Each row is mirrored to a JSONL file under `data/` (decisions.jsonl,
trades.jsonl, pnl.jsonl) for human-friendly auditing.

`scripts/export_audit_bundle.py` writes a self-contained, **secret-redacted**
dump to `export/<timestamp>/`:

```
export/<ts>/
├── config.json       # active config + safe env snapshot (no secret values)
├── decisions.json    # last N decisions (full Pydantic payload)
├── decisions.csv     # flat view of the same for spreadsheets
├── orders.json       # last N execution results across all modes
├── orders.csv
├── pnl.json          # PnL snapshots history
├── pnl.csv
└── errors.json       # structured errors recorded by the agent
```

## Repository structure

```
kraken-alpha-agent/
├── README.md
├── DISCLAIMER.md
├── PLAN.md
├── CLI_VALIDATION.md
├── config.yaml / config.example.yaml
├── .env.example
├── pyproject.toml / requirements.txt
├── docs/
│   ├── DEMO_SCRIPT.md
│   └── SUBMISSION.md
├── scripts/
│   ├── check_kraken_cli.py
│   ├── probe_xstocks.py
│   ├── rank_xstocks.py
│   ├── dry_run_once.py
│   ├── run_agent_loop.py
│   ├── paper_smoke_test.py
│   ├── analyze_paper_run.py
│   └── export_audit_bundle.py
├── src/
│   ├── actionability.py
│   ├── config.py
│   ├── dashboard/  (FastAPI + Jinja2)
│   ├── execution.py
│   ├── features.py
│   ├── kraken_cli.py
│   ├── llm_explainer.py
│   ├── logger.py
│   ├── main.py
│   ├── market_data.py
│   ├── paper_run_analysis.py
│   ├── pnl.py
│   ├── portfolio.py
│   ├── ranking.py
│   ├── regime.py
│   ├── risk.py
│   ├── schemas.py
│   ├── storage.py
│   ├── strategies/  (momentum / breakout / mean_reversion / ensemble)
│   ├── universe.py
│   └── utils.py
├── tests/  (16 files, 96 tests)
└── data/.gitkeep
```

## Acceptance criteria (condensed)

1. Autonomous xStocks trading agent powered by Kraken CLI.
2. Real xStocks market data via Kraken CLI (`tokenized_asset`).
3. Modular strategy engine (momentum, breakout, mean reversion + ensemble).
4. Liquidity-aware ranking module driving a dynamic universe.
5. Calibrated actionability layer (BUY threshold, SELL exit-only, no-short
   by default, liquidity dampener).
6. Risk manager with allowlist, spread/regime guards, drawdown/exposure
   caps, cooldown, hourly trade limiter, **live triple opt-in**.
7. Three execution modes (`dry_run` / `paper` / `live`) with paper-init
   guard.
8. Local SQLite + JSONL audit trail plus exportable audit bundle.
9. FastAPI dashboard with Actionability, Ranking, Decisions, Trades, PnL
   pages and matching JSON routes.
10. Optional Featherless LLM explainer (OpenAI-compatible API).
11. **96/96 tests green**; CI-friendly mock transport.
12. Submission docs (README, DISCLAIMER, PLAN, DEMO_SCRIPT, SUBMISSION,
    CLI_VALIDATION).

## Submission checklist

- [x] Secret audit clean — no credentials in tracked files.
- [x] README judge-ready (Quickstart, Architecture, Modes, Calibration,
      Safety, Submission).
- [x] `docs/DEMO_SCRIPT.md` finalised.
- [x] `docs/SUBMISSION.md` finalised (this file).
- [x] `pytest` is green (96/96).
- [x] `python scripts/dry_run_once.py` runs end-to-end.
- [x] Dashboard probed on `/`, `/ranking`, `/actionability`, `/health`.
- [x] `python scripts/export_audit_bundle.py` writes an `export/<ts>/`
      bundle on demand.
- [ ] Kraken paper account initialised by the user (one-time, manual:
      `wsl -- bash -lc "kraken paper init --balance 10000 --currency USD --yes"`).
- [ ] GitHub public push performed by the user (no remote configured in
      this freeze; see README submission steps).
- [ ] 90-second demo video recorded against `docs/DEMO_SCRIPT.md`.
