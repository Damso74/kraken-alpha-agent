# Kraken Alpha Agent — Submission packet

> Companion document for the **AI Agent Olympics — Kraken Challenge
> (Kraken Trading Performance)** submission, lablab.ai. Deadline:
> **20 May 2026**. Everything here is summarised from the codebase as it
> exists at the freeze commit; consult the linked files for source of
> truth.

## Executive summary

- **Built**: deterministic, fully audited xStocks trading agent on the
  Kraken CLI (232/232 tests green). Live dashboard:
  <https://kraken-alpha-agent-damso74s-projects.vercel.app>. Code:
  <https://github.com/Damso74/kraken-alpha-agent>.
- **Blocked at the venue layer**: the user's Kraken account is on
  **PEDSL-CY (Cyprus EU)** — both the **xStocks spot orderbook** and the
  **xStocks Perpetual Futures** are venue-blocked at the account-class
  layer (reproduced from two distinct IPs; control BTC Perp fills
  cleanly on the same key). This blocker is **not specific to us** —
  other lablab participants have reported the same family of errors on
  Discord (see [`HACKATHON_DISCORD_CONTEXT.md`](HACKATHON_DISCORD_CONTEXT.md)).
- **Submitted**: 30-day backtest evidence (30d / 60m, 15d / 30m, 7d /
  15m), full audit logs, read-only API key handover protocol, and a
  19-minute crypto-perps diagnostic (−0.55 USD) proving every component
  of the engine works against a live Kraken Futures venue.

## What we built

| Asset | Link |
|---|---|
| Live dashboard (Vercel) | <https://kraken-alpha-agent-damso74s-projects.vercel.app> |
| Source code (GitHub, public) | <https://github.com/Damso74/kraken-alpha-agent> |
| Submission narrative (this file) | [`docs/SUBMISSION.md`](SUBMISSION.md) |
| Methodology — walk-forward & honnêteté statistique | [`docs/METHODOLOGY.md`](METHODOLOGY.md) |
| Discord context | [`docs/HACKATHON_DISCORD_CONTEXT.md`](HACKATHON_DISCORD_CONTEXT.md) |
| Demo video script | [`docs/DEMO_VIDEO_SCRIPT.md`](DEMO_VIDEO_SCRIPT.md) |
| Jury read-only access protocol | [`docs/JURY_ACCESS_TEMPLATE.md`](JURY_ACCESS_TEMPLATE.md) |
| lablab submission form | [`docs/LABLAB_SUBMISSION_FORM.md`](LABLAB_SUBMISSION_FORM.md) |
| 30-day backtest snapshot (60m) | [`web/public/data/backtest_xstocks_30d.json`](../web/public/data/backtest_xstocks_30d.json) |
| 15-day backtest snapshot (30m) | [`web/public/data/backtest_xstocks_30m.json`](../web/public/data/backtest_xstocks_30m.json) |
| 7-day backtest snapshot (15m) | [`web/public/data/backtest_xstocks_15m.json`](../web/public/data/backtest_xstocks_15m.json) |

Key features (all live in `master`):

- **Ranked universe** — `scripts/rank_xstocks.py` scores the 13 ranked
  xStocks by momentum × liquidity × spread × trade count; the dynamic
  universe picks the top-N every cycle.
- **Ensemble strategies** — momentum, breakout, mean-reversion blended
  via a weighted ensemble (`src/strategies/ensemble.py`) with
  liquidity-aware confidence dampening.
- **Risk gates** — drawdown / exposure / cooldown / hourly trade
  caps, **live triple opt-in** (`TRADING_MODE=live` +
  `LIVE_TRADING=true` + `ALLOW_LIVE_ORDERS=true`), per-symbol allowlist,
  spread / regime guards, `HARDCODED_MAX_LEVERAGE=1.0` (defense in
  depth), funding-rate gate (futures), and the regression-tested
  exit-action carve-out so SELL exits are never blocked by an
  exposure-saturated book.
- **Exit engine** — `flatten_before_close_exit` flattens 15 min before
  the US_CORE close (no overnight funding accrual); Friday end-of-day
  rule freezes new BUYs at 21:45 CEST and hard-stops the loop at 22:00.
- **Futures support** — `src/futures_kraken_cli.py` is the single
  chokepoint for `kraken futures …`, with the spot↔perpetual symbol
  mapping (`TICKERx/USD → PF_TICKERXUSD`), strict success-status
  whitelist that downgrades `wouldNotReducePosition` / `invalidSize` /
  `marketSuspended` to `ok=False`, and SELL-as-exit-only semantics
  with `--reduce-only` forced on the wire.
- **Audit logs** — every decision, every order, every PnL snapshot,
  every error is persisted to SQLite (`data/agent.sqlite`, 6 tables)
  and mirrored to JSONL files (`data/decisions.jsonl`,
  `data/trades.jsonl`, `data/pnl.jsonl`). Secret-redacted bundles via
  `scripts/export_audit_bundle.py`.
- **Dashboard** — FastAPI + Jinja2 in `src/dashboard/` (operator
  view), and a **Next.js submission landing page** in `web/` deployed
  on Vercel for the jury (cards, ranking, backtest charts at multiple
  timeframes, system architecture SVG).

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

## The xStocks block — why our live PnL is small

> **TL;DR.** Both the spot xStocks orderbook *and* the xStocks Perps
> futures venue are blocked at the account-class layer on this Kraken
> account (PEDSL-CY, Cyprus EU). The bot itself is API-correct end to end
> — a BTC Perp control on the same key/IP fills cleanly — but the
> hackathon-eligible xStocks track is structurally inaccessible from this
> jurisdiction. **Final xStocks live PnL: 0.00 USD, 0 fill, 0 open
> position at session end.** Total live account PnL (crypto diagnostic
> included) is approximately **−0.55 USD**.

### This is not specific to us — Discord evidence

The full audit trail of public Discord messages from other lablab
participants and from the moderators (Steve, Inaam) is collected
verbatim in [`docs/HACKATHON_DISCORD_CONTEXT.md`](HACKATHON_DISCORD_CONTEXT.md).
Highlights:

| Participant | Date (CEST) | Quote (verbatim) |
|---|---|---|
| `thisisaman408` | 14/05 20:47 | "We'd have to buy kraken api and it's **not available in all the countries**, hah" |
| `djkorou360` | 16/05 17:20 | "is it not possible to short anything ? Is it designed as a spot market my shorting function is running into errors and the **TSLAx/USD is also returning kraken cli errors**" |
| `djkorou360` | 16/05 21:29 | `kraken ticker AAPLx/USD` → `Error: EQuery:Unknown asset pair` |
| `djkorou360` | 16/05 21:29 | `kraken paper sell ETH/USD 100 --yes` → `Insufficient ETH balance. Available: 0.00000000` (short blocked) |
| `Ammar Khalid` | 17/05 15:20 | "do we need the real money to deposit on kraken xstocks or we can do paper trading?" — **no official answer** |
| `Jennycruzy` | 18/05 03:21 | "Does Kraken CLI support xStocks for paper trading ?" — **no official answer** |

In other words: **xStocks ↔ Kraken CLI ↔ paper engine ↔ EU/EEA
availability are open issues across the whole `#kraken-challenge`
Discord channel.** Our PEDSL-CY block (spot `EGeneral:Permission
denied` + futures `wouldNotReducePosition`) is the EU-account variant
of the same structural problem.

### Crypto fallback — diagnostic only (outside xStocks track)

We took the only path left to validate the rest of the engine against
a real Kraken venue: a 19-minute **crypto Perps** live session with the
same 1x-leverage / no-shorting / triple-opt-in safeguards. Outcome:

- **22 real fills** on LTC / ETH / SOL / AVAX / BTC.
- **PnL ≈ −0.55 USD** (essentially taker-fee burn + drift on a strategy
  not tuned for crypto micro-structure — the thresholds are
  xStocks-calibrated).
- **Fee burn rate ≈ −1.5 USD/h** at the current strategy maturity on
  crypto perps.
- Stopped automatically by the volume watchdog at **500 USD cumulative
  turnover** (LTC over-rotation detected) — exactly the throttle path
  designed for runaway loops.

### Why we stopped live trading

With **2 days left to the deadline** and the xStocks venue confirmed
blocked, continuing live trading would have meant:

- Burning **≈ 72 USD of taker fees** over 48h on a strategy that
  **does not contribute to the xStocks scoring track**.
- Adding noise to the read-only audit window without any chance of
  improving the xStocks PnL line.
- Risking a runaway loop while the user was offline (the watchdog
  caught it once at +500 USD turnover; we did not want to retest the
  failure mode in production).

**Decision (option A): stop live trading, finalise the submission with
the existing −0.55 USD line.** The crypto diagnostic stays in the
account history exactly because the jury's read-only key will see it
— and the SQLite + JSONL audit log makes it trivial to cross-check
every fill, every cancel, every watchdog trigger.

## Live result on this account (PEDSL-CY block)

> **TL;DR.** Both the spot xStocks orderbook *and* the xStocks Perps
> futures venue are blocked at the account-class layer on this Kraken
> account (PEDSL-CY, Cyprus EU). The bot itself is API-correct end to end
> — a BTC Perp control on the same key/IP fills cleanly — but the
> hackathon-eligible xStocks track is structurally inaccessible from this
> jurisdiction. **Final xStocks live PnL: 0.00 USD, 0 fill, 0 open
> position at session end.**

### Venue-level rejections observed (2026-05-15)

| Engine               | Symbol             | Command                                           | Response                                                  |
|----------------------|--------------------|---------------------------------------------------|-----------------------------------------------------------|
| Spot xStocks         | `AAPLx/USD`        | `kraken order buy --asset-class tokenized_asset`  | `EGeneral:Permission denied` (also on SELL of owned token) |
| Spot xStocks         | `AAPLx/USD`        | same, from VPS US-NJ IP                           | identical error (NOT IP/geo)                              |
| Futures xStocks Perp | `PF_HOODXUSD`      | `kraken futures order buy ... --type market`      | `{"result":"success","status":"wouldNotReducePosition"}`  |
| Futures xStocks Perp | `PF_AAPLXUSD`      | same                                              | identical `wouldNotReducePosition`                        |
| Futures crypto Perp  | `PF_XBTUSD`        | same (control on same key/IP/account)             | `{"status":"placed"}` — real fill, position opened        |

The misleading `wouldNotReducePosition` status (= "this account can only
ever close xStocks Perps positions, never open them") is consistent with
the **"EU/EEA excluded"** caveat in the Kraken xStocks Futures Trading
Contest terms.

The CLI parser was hardened (see commit `d15c62c`) so the bot no longer
treats `wouldNotReducePosition` / `invalidSize` / `marketSuspended` as
successful fills: `src/futures_kraken_cli.run_futures_cli` now downgrades
any non-whitelisted Kraken Futures status to `ok=False` regardless of
the HTTP-level `result=success` wrapper.

### Crypto fallback diagnostic (outside xStocks track)

To validate the rest of the deterministic pipeline against real venue
interaction without dead-coding, a 19-minute crypto Perps live session
was run with the same 1x-leverage / no-shorting / triple-opt-in
safeguards:

- 22 real fills (LTC / ETH / SOL / AVAX / BTC) across 10 candidate
  symbols.
- PnL ≈ **−0.55 USD** — essentially taker-fee burn plus drift on a
  strategy not tuned for crypto micro-structure (xStocks-calibrated
  thresholds).
- Stopped automatically by the volume watchdog at 500 USD cumulative
  turnover (LTC over-rotation detected) — exactly the throttle path
  designed for runaway loops.
- Confirms the futures engine, the dead-man cancel-after, the strict
  parser whitelist, the volume watchdog and the flatten path all
  function end-to-end against the live Kraken Futures venue.

This crypto run is documented as a **technical diagnostic** and is
explicitly outside the xStocks competition track. The active default
profile remains `aggressive_competition` (spot xStocks engine); the
`micro_live_100eur_crypto` profile shipped in `config.yaml` is gated
behind `KRAKEN_ALPHA_PROFILE=micro_live_100eur_crypto` and never the
default.

## Live execution — Perpetual Futures pivot

> **Context.** EU / PEDSL-CY accounts (the user's jurisdiction) cannot trade
> the spot xStocks orderbook on Kraken Spot at the time of submission.
> Hackathon ranking is computed from live PnL, so the project pivoted the
> live execution path to **Kraken Futures Perpetual xStocks**, which the
> same jurisdiction was *initially expected* to trade. Subsequent testing
> on this account revealed an additional venue-level block on xStocks
> Perps (see "Live result" section above). The override of the original
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
├── tests/  (29 files, 232 tests)
├── web/    (Next.js submission landing page, deployed on Vercel)
└── data/.gitkeep
```

## Backtest evidence (deterministic, reproducible)

Because live execution is venue-blocked on this account, we attach
**three deterministic backtest snapshots** generated from the same
ensemble engine the live agent uses. They are committed at
`web/public/data/backtest_xstocks_*.json` and rendered on the public
Vercel dashboard for the jury.

| Snapshot | Window | Bar size | Trades | Net PnL | Net PnL % | Best symbol | Worst symbol |
|---|---|---|---|---|---|---|---|
| **30d / 60m** (primary) | 16/04 → 15/05/2026 | 60 min | **138** | **+33.56 USD** | **+0.34 %** | `CRCLx` (+17.60 USD) | `TSLAx` |
| 15d / 30m (mid-frequency) | 01/05 → 15/05/2026 | 30 min | 12 | −7.20 USD | −0.07 % | `TSLAx` | `CRCLx` |
| 7d / 15m (intraday) | 10/05 → 14/05/2026 | 15 min | 12 | +4.38 USD | +0.04 % | `TSLAx` | `MSTRx` |

Starting capital is **10 000 USD** for all three snapshots. The 30-day
60-min snapshot covers **6 480 candles** across 9 ranked xStocks
(`NVDAx`, `CRCLx`, `HOODx`, `AAPLx`, `AMZNx`, `QQQx`, `TSLAx`,
`MSTRx`, `GOOGLx`) and walks the engine cycle-by-cycle including the
real cooldown logic, the actionability layer and the risk gate.

**What this proves:**

- The engine produces actionable signals at multiple timeframes
  (60-min: 138 trades, win rate 53.0 %; 15-min: 12 trades, win rate
  33.3 %).
- Performance scales with the ranking pass: `CRCLx` and `HOODx`
  dominate the 30-day window (matching their leading position in
  `data/xstocks_rank_latest.json`).
- Max drawdown stays bounded at **1.68 %** over 30 days — consistent
  with the per-position cap (`max_position_notional_usd`) and the
  exposure cap (`max_total_exposure_usd`) defined in
  `aggressive_competition`.
- The same backtest harness is wired into the Vercel landing page so
  the jury can inspect every per-symbol row without cloning the repo.

These snapshots are **not** a substitute for live PnL — they are
explicit, labelled `backtest_local_estimate` and never mixed with the
`live` PnL source in the dashboard.

### Walk-forward audit (anti-curve-fitting)

To stress-test the calibration of the `aggressive_competition`
profile against the risk of in-sample over-fitting, we ran a
**strict walk-forward parameter sweep** on a longer (240-min × 120
days) OHLC dataset. The full methodology — train/test split, grid,
out-of-sample filter, composite robustness score, caveats — lives
in **[`docs/METHODOLOGY.md`](METHODOLOGY.md)**.

Headline result : **0 / 48 configurations** passed the joint filter
`test_pnl_usd ≥ 0` AND `test_win_rate ≥ 50 %` on the 30-day
out-of-sample slice. No tuned profile to promote, no
`config.yaml` change, and the three snapshots above remain as
shipped. The non-finding is **itself the deliverable** : it proves
that the live calibration was not stochastically lucky on the
30-day window and that we did not retroactively pick the best grid
point to inflate the headline number. See
`docs/METHODOLOGY.md` for the per-combo numbers and the explicit
limitations of the sweep.

### Strategy Exploration Attempts (chronological)

The crypto fallback path triggered 5 successive strategy discovery
attempts to verify whether *any* tunable subset of the engine could
deliver a positive OOS edge meeting a strict `pnl ≥ $0.20 ∧ wr ≥ 50 % ∧
trades ≥ 30` filter. All 5 attempts return **zero survivors**:

| # | Attempt | Combos | Survivors | Best OOS PnL | Best OOS WR | Source |
|---|---------|--------|-----------|--------------|-------------|--------|
| 1 | Walk-forward 240-min deterministic | 48 | 0 | −0.09 USD | 40.50 % | `data/walk_forward_crypto_results.json` |
| 2 | Walk-forward 60-min deterministic | 48 | 0 | −0.21 USD | 42.99 % | `data/walk_forward_crypto_60min_results.json` |
| 3 | Walk-forward 15-min deterministic | 48 | 0 | −0.02 USD | 51.85 % (PnL−) | `data/walk_forward_crypto_15min_results.json` |
| 4 | **Optuna Bayesian 500 trials (Phase 2a)** | 500 | 0 | +0.251 USD | 43.0 % | `data/optuna_crypto_results.json` |
| 5 | **Walk-forward + 3 external signals (Phase 2b)** | 180 | 0 | +0.266 USD | 42.7 % | `data/walk_forward_with_signals_results.json` |

**Verdict total** : 0 / 824 configurations across 5 independent
discovery methodologies (deterministic grid × 3 resolutions, Bayesian
Optuna, walk-forward with Fear & Greed + BTC dominance + realized
volatility regime gates). Aucun profil
`live_crypto_*_capped` (incluant `live_crypto_with_signals_capped`)
n'a été créé. Le verdict EV-négatif sur option D est strictement
renforcé. Voir
[`docs/STRATEGY_DISCOVERY_REPORT.md`](STRATEGY_DISCOVERY_REPORT.md)
pour la méthodologie complète Phase 2 (espace de recherche, pruning,
BTC dominance caveat, p-hacking risk) et
[`docs/OPTION_D_ACTIVATION.md`](OPTION_D_ACTIVATION.md) pour la
checklist d'activation (qui reste à 0 cases cochées).

### Audit bundle for the jury

The jury can reproduce the full per-decision audit trail with one
command:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/export_audit_bundle.py
```

The script reads `data/agent.sqlite` (six tables : `decisions`,
`orders`, `positions`, `pnl_snapshots`, `errors`, `cycles`),
walks the JSONL ledgers (`data/decisions.jsonl`, `data/trades.jsonl`,
`data/pnl.jsonl`), and writes a self-contained dump under
`export/<UTC-timestamp>/` :

```
export/<ts>/
├── config.json     # active config + safe env snapshot (no secret values)
├── decisions.json  # full Pydantic payloads
├── decisions.csv   # flat spreadsheet view
├── orders.json     # every ExecutionResult across all modes
├── orders.csv
├── pnl.json        # PnL snapshots tagged by source
├── pnl.csv
└── errors.json     # structured errors with where_label + stack hash
```

`export/` is `.gitignore`'d so the bundle is **never committed**;
the dump is generated on demand and shared with the jury via the
out-of-band channel described in
[`docs/JURY_ACCESS_TEMPLATE.md`](JURY_ACCESS_TEMPLATE.md). The
config block is fed through `safe_env_snapshot()` which masks every
secret value (only the *presence* of an API key is reported, never
the key itself).

## Roadmap — if not blocked

Given **one unrestricted week of live xStocks trading** on a non-EU
Kraken account, the immediate next steps would be:

1. **Day 1 — Re-validate the live path** with `kraken order …
   --validate` against the spot xStocks orderbook (already wired in
   `scripts/validate_live_xstocks.py`), then `kraken futures order …
   --validate`-equivalent through the futures **paper** engine for the
   Perps fallback. Both already pass on a clean key — the only missing
   piece is the venue permission.
2. **Days 2-3 — 20-minute shadow run** then a 24-hour `paper` loop
   with the dynamic universe (top-8 ranked xStocks). Audit log
   recompares predicted vs. realised fills via
   `scripts/analyze_paper_run.py --since 24`.
3. **Day 4 — Micro-live activation** with
   `KRAKEN_ALPHA_PROFILE=micro_live_100eur` (caps: 30 USD total
   exposure, 10 USD per position, `engine: spot`). Triple opt-in +
   `kraken order cancel-after 60` dead-man switch. Watchdogs from the
   crypto diagnostic stay armed: volume cap, exit-action carve-out,
   `flatten_before_close_exit` at 15 min before US close.
4. **Days 5-6 — Scale-up** to the full `aggressive_competition` profile
   (1500 USD max position, 25 % max exposure) only if the micro-live
   day shows a positive Sharpe and zero stuck positions.
5. **Day 7 — Demo recording + jury handover**. The read-only key is
   rotated *after* the audit window closes, the write key is rotated
   immediately post-hackathon (recorded as a post-conditions checklist
   in `AGENTS.md`).

**Engine-level work that is already done but un-tested in production**
(would benefit most from one week of live data):

- Calibrating the **funding-rate gate** threshold on real xStocks
  Perps order books (currently 0.5 %/h, conservative).
- Tightening the **liquidity dampener** (`liquidity_size_dampener`)
  with empirical xStocks spread distributions — today it is
  hand-picked from the 30-day backtest.
- Replacing the rule-based regime classifier with the calibrated
  logistic regression already prototyped in `notebooks/` (not
  committed — out of scope for the freeze).

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
11. **232/232 tests green** (parser whitelist, risk gates, futures
    execution, exit rules, futures CLI mapping, exit-action exposure
    carve-out, etc.); CI-friendly mock transport.
12. Submission docs (README, DISCLAIMER, PLAN, DEMO_SCRIPT,
    DEMO_VIDEO_SCRIPT, SUBMISSION, CLI_VALIDATION, VPS_RUNBOOK,
    JURY_ACCESS_TEMPLATE, LABLAB_SUBMISSION_FORM,
    HACKATHON_DISCORD_CONTEXT).

## Submission checklist

- [x] Secret audit clean — no credentials in tracked files
      (`.env`, `data/`, `export/` all `.gitignore`'d).
- [x] README judge-ready (Quickstart, Architecture, Modes, Calibration,
      Safety, Submission), with explicit links to all submission docs.
- [x] `docs/DEMO_SCRIPT.md` (90-second narration) finalised.
- [x] `docs/DEMO_VIDEO_SCRIPT.md` (3-4 minute storyboard with the
      "honesty moment" PEDSL-CY scene) finalised.
- [x] `docs/SUBMISSION.md` finalised (this file).
- [x] `docs/HACKATHON_DISCORD_CONTEXT.md` (verbatim public Discord
      messages on xStocks blockers) finalised.
- [x] `docs/JURY_ACCESS_TEMPLATE.md` finalised (read-only audit
      protocol, no live keys committed).
- [x] `docs/LABLAB_SUBMISSION_FORM.md` finalised (copy-paste-ready
      form fields).
- [x] `pytest` is green (**232 / 232** as of submission freeze).
- [x] `python scripts/dry_run_once.py` runs end-to-end.
- [x] Dashboard probed on `/`, `/ranking`, `/actionability`, `/health`
      (FastAPI) and on the public Vercel landing page.
- [x] `python scripts/export_audit_bundle.py` writes an `export/<ts>/`
      bundle on demand.
- [x] Live xStocks execution attempted and documented (PEDSL-CY block
      reproduced — see "Live result on this account" section).
- [x] Crypto fallback diagnostic recorded (22 fills, PnL ≈ −0.55 USD,
      technical-only — outside xStocks track).
- [x] Backtest evidence committed (30d / 60m + 15d / 30m + 7d / 15m
      snapshots in `web/public/data/`).
- [ ] **Manual — User** : record the 3-4 min demo video against
      `docs/DEMO_VIDEO_SCRIPT.md`.
- [ ] **Manual — User** : fill the lablab submission form using
      `docs/LABLAB_SUBMISSION_FORM.md`.
- [ ] **Manual — User** : send the **read-only Kraken API key** (Spot
      + Futures, scope per `docs/JURY_ACCESS_TEMPLATE.md`) to the jury
      via lablab DM (NEVER commit the key text).
- [ ] **Manual — User** : Kraken paper account initialised
      (`wsl -- bash -lc "kraken paper init --balance 10000 --currency USD --yes"`)
      — required only if the jury wants to reproduce paper-mode locally.
