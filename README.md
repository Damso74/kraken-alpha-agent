# Kraken Alpha Agent · Kraken Sentinel

> Autonomous, fully audited xStocks trading agent built on the
> [Kraken CLI](https://www.kraken.com/kraken-cli) for the
> **AI Agent Olympics — Kraken Challenge (Kraken Trading
> Performance)** track. Deterministic engine, three modes (`dry_run` /
> `paper` / `live`) with a live triple opt-in, full audit trail in
> SQLite + JSONL, and a public Vercel dashboard for the jury.

**Public alias:** `Kraken Sentinel` · **Codename:** `Kraken Alpha Agent`

---

## Status — frozen submission branch, 2026-08-19

> **This branch is the hackathon submission, frozen at 2026-05-19.** It is kept
> as-is so a judge sees exactly what was submitted. It is not maintained and it
> is not a live trading system.
>
> The post-hackathon research that continued on
> [`phase30/observation-ops-ux`](https://github.com/Damso74/kraken-alpha-agent/tree/phase30/observation-ops-ux)
> is **closed**: thirty phases, 872 engine configurations under walk-forward
> out-of-sample, 18 event-study hypotheses — **0 tradable signal, 0 OOS
> candidate**. The full verdict, including what it does *not* prove, is in
> [`reports/PHASE31_FINAL_VERDICT.md`](https://github.com/Damso74/kraken-alpha-agent/blob/phase30/observation-ops-ux/reports/PHASE31_FINAL_VERDICT.md)
> on that branch.
>
> The account class (PEDSL-CY, Cyprus EU) blocks xStocks execution at the venue
> layer, which is why the live PnL below is small — and, as the closing audit
> established, why none of the candidate signals could have been net positive
> here anyway: the best one returns +0.79 pp at 72 h against a 1.00 % pessimistic
> round trip.

---

## For hackathon judges — start here

| Asset | Link |
|---|---|
| **Quickstart for jury (5-10 min read)** | [`SUBMISSION_QUICKSTART.md`](./SUBMISSION_QUICKSTART.md) |
| Live dashboard (Vercel, public) | <https://kraken-alpha-agent-damso74s-projects.vercel.app> |
| Submission narrative | [`docs/SUBMISSION.md`](./docs/SUBMISSION.md) |
| Methodology (walk-forward audit) | [`docs/METHODOLOGY.md`](./docs/METHODOLOGY.md) |
| Demo video script (3-4 min) | [`docs/DEMO_VIDEO_SCRIPT.md`](./docs/DEMO_VIDEO_SCRIPT.md) |
| Discord context (xStocks blockers, verbatim) | [`docs/HACKATHON_DISCORD_CONTEXT.md`](./docs/HACKATHON_DISCORD_CONTEXT.md) |
| Read-only API key handover protocol | [`docs/JURY_ACCESS_TEMPLATE.md`](./docs/JURY_ACCESS_TEMPLATE.md) |
| lablab submission form (copy-paste-ready) | [`docs/LABLAB_SUBMISSION_FORM.md`](./docs/LABLAB_SUBMISSION_FORM.md) |
| VPS runbook | [`docs/VPS_RUNBOOK.md`](./docs/VPS_RUNBOOK.md) |

### Honest one-liner

The user's Kraken account is on **PEDSL-CY (Cyprus EU)**, so **both
the spot xStocks orderbook and the xStocks Perpetual Futures are
venue-blocked at the account-class layer**. The engine is correct end
to end (a BTC Perp control on the same key fills cleanly; 232 / 232
tests green at the 2026-05-19 submission freeze, 330 / 330 today),
**other lablab participants have publicly reported the same xStocks
errors** (see `docs/HACKATHON_DISCORD_CONTEXT.md`), and
the audit-ready PnL is documented honestly in `docs/SUBMISSION.md`
*"The xStocks block — why our live PnL is small"*.

### Quick-start — read-only inspection mode (no trading, no Kraken account)

```powershell
git clone https://github.com/Damso74/kraken-alpha-agent.git
cd kraken-alpha-agent
python -m venv .venv
.venv\Scripts\Activate.ps1                    # source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
copy .env.example .env                        # cp .env.example .env

# Probe the Kraken CLI (works without an API key, falls back to deterministic mock)
python scripts/check_kraken_cli.py

# Full deterministic test suite (~5 s)
pytest                                        # expected: 330 passed

# One full agent cycle, no order placed (uses the mock transport if no CLI is installed)
python scripts/dry_run_once.py

# Local FastAPI dashboard (http://127.0.0.1:8000)
uvicorn src.dashboard.app:app --reload
```

No Kraken account, no API key, no WSL install required for the dry-run
path — the CLI wrapper falls back to a deterministic mock so judges
can audit the agent's decision pipeline end-to-end on a fresh machine.

---

## Disclaimer

This project is for **hackathon and educational purposes only**. It is **not
financial advice**. Live trading involves risk. The default operating mode
is `dry_run` — no order can leave the process without an explicit triple
opt-in. See [`DISCLAIMER.md`](./DISCLAIMER.md) for the full text.

---

## Quickstart for judges (full path)

```powershell
git clone https://github.com/Damso74/kraken-alpha-agent.git
cd kraken-alpha-agent
python -m venv .venv && .venv\Scripts\Activate.ps1   # source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
copy .env.example .env                               # cp .env.example .env
pytest                                               # 330 tests, ~15s
python scripts/dry_run_once.py                       # one full cycle, no orders
uvicorn src.dashboard.app:app --reload               # http://127.0.0.1:8000
```

No Kraken account, no API key, no WSL install required for the dry-run path —
the CLI wrapper falls back to a deterministic mock so judges can audit the
agent's decision pipeline end-to-end on a fresh machine.

For the full "paper competition" runbook see
[Competition simulation runbook](#calibration-knobs).

---

## What it does

1. Polls public xStocks market data from the Kraken CLI (or a deterministic
   mock when the CLI is missing).
2. Builds a small feature set per symbol (returns, volatility, spread,
   distance from 1h high/low, volume).
3. Classifies the **market regime**
   (TRENDING_UP / TRENDING_DOWN / RANGING / HIGH_VOLATILITY / LOW_LIQUIDITY / UNKNOWN).
4. Runs three independent **strategies** (momentum, breakout, mean reversion)
   and blends their votes via a weighted **ensemble**.
5. Asks the **risk manager**:
   - is the symbol on the allowlist?
   - confidence high enough?
   - spread reasonable?
   - drawdown / exposure within caps?
   - cooldown respected?
   - **for live mode: are all three opt-in flags set?**
6. Routes the approved action through the **execution layer**
   (`dry_run` / `paper` / `live`).
7. Persists each decision to **SQLite** + **JSONL** for audit, exposes a
   minimal **FastAPI dashboard**, and optionally generates an LLM
   explanation via **Featherless** (OpenAI-compatible API).

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ kraken_cli ──> market_data ──> features ──> regime ──> strategies ──> ensemble
│                                                                     │         │
│                                                                     ▼         │
│                                                              actionability    │
│                                                                     │         │
│                                                                     ▼         │
│                                                                    risk       │
│                                                                     │         │
│                                                                     ▼         │
│                                              execution (dry_run / paper / live)
│                                                                     │         │
│                                              storage ───────────────┴──> dashboard
└──────────────────────────────────────────────────────────────────────────────┘
```

## Architecture

| Layer            | File                         | Responsibility                                                 |
|------------------|------------------------------|----------------------------------------------------------------|
| Config           | `src/config.py`              | Pydantic-settings — `.env` + `config.yaml`, cached singleton   |
| Schemas          | `src/schemas.py`             | Pydantic models (Decision, RiskResult, ExecutionResult, …)     |
| Logger           | `src/logger.py`              | Structured logs with secret masking                            |
| Kraken CLI       | `src/kraken_cli.py`          | Subprocess wrapper, JSON parsing, **mock fallback**            |
| Market data      | `src/market_data.py`         | `get_ticker`, `get_ohlc`, `get_current_price`, `get_orderbook` |
| Universe         | `src/universe.py`            | xStocks allowlist + symbol normalisation                       |
| Features         | `src/features.py`            | Pure feature engineering                                       |
| Regime           | `src/regime.py`              | Rule-based regime classifier                                   |
| Strategies       | `src/strategies/*.py`        | momentum / breakout / mean_reversion / ensemble                |
| Actionability    | `src/actionability.py`       | BUY threshold, SELL exit-only, no-short, liquidity dampener    |
| Risk             | `src/risk.py`                | Single gate for any order — incl. live triple opt-in           |
| Execution        | `src/execution.py`           | `dry_run` / `paper` / `live` execution router                  |
| Portfolio + PnL  | `src/portfolio.py`, `pnl.py` | Local-estimate bookkeeping (clearly labelled)                  |
| LLM explainer    | `src/llm_explainer.py`       | Optional Featherless explanation (JSON only)                   |
| Storage          | `src/storage.py`             | SQLite (6 tables) + JSONL writers                              |
| Dashboard        | `src/dashboard/`             | FastAPI + Jinja2 trading-terminal style                        |
| Orchestrator     | `src/main.py`                | `run_one_cycle` / `run_loop`                                   |

## Strategy & actionability gates

- **Momentum** — leans on short-horizon returns (5m, 15m, 1h) with a saturating tanh-like
  squash. Strong moves score close to ±1.
- **Breakout** — proximity to the 1h high/low. Buys near the 1h high, sells near the
  1h low.
- **Mean reversion** — fades sharp 15m moves that do not match the 1h direction.
- **Ensemble v2** — competition-grade weighted blend with liquidity awareness:
  ```
  final_score = w_mom * momentum
              + w_brk * breakout
              + w_mr  * mean_reversion
              + w_liq * liquidity_score      (reinforces directional bias)
              - w_vol * volatility_penalty
              - w_spr * spread_penalty
  ```
  Action is `BUY` above the profile's `buy` threshold, `SELL` below `sell`,
  otherwise `HOLD`. Confidence is dampened by low liquidity and high volatility
  so a strong signal on a dead book does not produce an oversized position.
- **Actionability layer** (`src/actionability.py`) — sits **between** the
  ensemble and the risk manager and downgrades unsafe intents to `HOLD`
  before they ever reach the order builder: BUY below threshold,
  negative-opportunity veto, SELL exit-only (no short by default), SELL
  size clamp to the open quantity, and low-liquidity size dampener. Full
  knobs: [Calibration knobs](#calibration-knobs).

## Competition mode

The agent exposes a **profile system** so the same codebase can run in
defensive, balanced, or aggressive configurations without code changes.

### Profiles

`config.yaml` ships three profiles; the active one is selected by the
top-level `profile:` key or by the `KRAKEN_ALPHA_PROFILE` environment
variable (which wins over the file).

| Profile                  | Use case                              | Notable defaults                                                        |
|--------------------------|---------------------------------------|--------------------------------------------------------------------------|
| `balanced` (default)     | Reasonable thresholds, max 5 positions| `min_conf=0.30`, `max_position=$1500`, `max_trades_hour=20`, `buy=±0.20` |
| `aggressive_competition` | Higher activity for the Kraken track  | `min_conf=0.22`, `max_position=$2500`, `max_trades_hour=40`, `buy=±0.15` |
| `conservative_debug`     | Tight thresholds, max 2 positions     | `min_conf=0.45`, `max_position=$500`, `max_trades_hour=6`, `buy=±0.30`   |

**Live opt-in is profile-independent** — every profile still requires the
full triple opt-in to place a live order. A dedicated regression test
(`tests/test_risk_aggressive.py`) verifies this.

```powershell
# Switch profile for the current shell
$env:KRAKEN_ALPHA_PROFILE = "aggressive_competition"
python scripts/dry_run_once.py
```

### Ranking, dynamic universe, paper smoke test

```powershell
# 1. Rank xStocks (read-only, writes data/xstocks_rank_<ts>.json + .csv)
python scripts/rank_xstocks.py --top 5
python scripts/rank_xstocks.py --profile aggressive_competition --top 10

# 2. Switch to dynamic universe in config.yaml
#   universe:
#     mode: dynamic
#     top_n: 8
# The agent loop will run a ranking pass and trade only the top-N opportunities.
python scripts/dry_run_once.py

# 3. Paper smoke test (read-only by default — no order placed)
python scripts/paper_smoke_test.py
# Initialise the paper account (one-time, opt-in):
python scripts/paper_smoke_test.py --init
# Place a single mini paper order AAPLx/USD 0.001 (paper, never live):
python scripts/paper_smoke_test.py --place-test-order
```

The dashboard surfaces a **Competition** section that reads
`data/xstocks_rank_latest.json` (TTL 60 s) and a `/ranking` JSON endpoint
for the raw payload. Banners at the top of the page declare the active
profile, the PnL source (`local_estimate` / `paper` / `live`) and whether
the paper account is initialised.

### Calibration knobs

The actionability layer sits **between** the ensemble and the risk manager.
It downgrades unsafe / unwarranted intents to `HOLD` before they ever reach
the order builder. The knobs live under `trading:` in `config.yaml`
(safe defaults shown):

| Key                              | Default | Effect                                                                                    |
|----------------------------------|---------|-------------------------------------------------------------------------------------------|
| `min_opportunity_score_buy`      | `0.18`  | `BUY` requires `final_score ≥ this`. Below ⇒ HOLD, reason `below_buy_threshold`.          |
| `min_opportunity_score_sell`     | `0.18`  | `SELL` requires `|final_score| ≥ this`. Below ⇒ HOLD, reason `below_sell_threshold`.      |
| `sell_exit_only`                 | `true`  | SELL only allowed when the symbol has an open long position.                              |
| `shorting_enabled`               | `false` | Must be `true` **and** env `SHORTING_ENABLED=true` to open a short. Otherwise SELL→HOLD.  |
| `no_trade_if_negative_opportunity` | `true`| Catches edge cases where BUY would fire on a negative score.                              |
| `liquidity_size_dampener`        | `0.5`   | If `liquidity_score < dampener` the suggested size is multiplied by …                     |
| `liquidity_size_factor`          | `0.5`   | … this factor (default halves the size on low liquidity).                                 |

Numeric thresholds can also be overridden via env (`MIN_OPPORTUNITY_SCORE_BUY`,
`MIN_OPPORTUNITY_SCORE_SELL`). **Shorting is the one exception**:
`SHORTING_ENABLED` and `trading.shorting_enabled` are kept independent on
purpose — both must be opted-in, in two distinct places, before any short
is permitted.

In addition, `src/execution.py` gates paper orders behind a 30-second
cached probe of `kraken paper status`. If the paper account is not
initialised, the execution layer returns
`status="blocked_paper_not_initialized"` and **never calls the CLI**.

### Competition simulation runbook

```powershell
# 1. Initialise the paper account (manual, one-time, $0 real)
wsl -- bash -lc "kraken paper init --balance 10000 --currency USD --yes"
python scripts/paper_smoke_test.py    # verifies initialisation

# 2. Snapshot the xStocks opportunity surface
python scripts/rank_xstocks.py --top 8

# 3. Switch to a dynamic universe (edit config.yaml)
#    universe:
#      mode: dynamic
#      top_n: 8

# 4. Run the paper loop (Ctrl+C to stop)
$env:TRADING_MODE = "paper"
python scripts/run_agent_loop.py

# 5. Analyse the session (Markdown + JSON in data/)
python scripts/analyze_paper_run.py --since 1
```

`analyze_paper_run.py` writes a Markdown executive summary plus a JSON
payload. Reading order:

- timestamped report: `data/paper_run_report_<ts>.md` / `.json`
- stable "latest" copy:   `data/paper_run_report_latest.md` / `.json`

When there is no data in the window the report still gets written and
prints a friendly `No paper run data yet` line.

## Modes

| Mode      | Behaviour                                                                                                          |
|-----------|--------------------------------------------------------------------------------------------------------------------|
| `dry_run` | Default. The agent logs every decision but **never** invokes a trading command.                                    |
| `paper`   | Calls `kraken paper buy/sell ...` when the CLI is installed; otherwise falls back to a clearly labelled simulation.|
| `live`    | Calls `kraken order buy/sell ...`. **Requires the full triple opt-in** (see below) and only places approved sizes. |

### Paper trading limitations (xStocks)

- **Read-only xStocks market data is confirmed** end-to-end against
  `kraken 0.3.2` (52/52 ticker / ohlc / orderbook / trades calls succeeded
  with `--asset-class tokenized_asset`).
- **Paper xStocks support must be confirmed locally.** As of `kraken 0.3.2`,
  `kraken paper buy/sell` does **not** expose `--asset-class`, so submitting
  a tokenized pair like `AAPLx/USD` returns `EQuery:Unknown asset pair`. When
  this happens, `scripts/paper_smoke_test.py --place-test-order` logs:
  `Kraken CLI paper engine may not support xStocks; falling back to local
  simulation.` and the agent loop transparently routes paper failures
  through the deterministic `_simulate_paper_fill` path in
  `src/execution.py`, so the competition cycle keeps producing fills, P&L
  and audit rows.

## Setup

> Python 3.11+ recommended.

```powershell
# 1. Clone or download this folder, then
python -m venv .venv
.venv\Scripts\Activate.ps1    # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
copy .env.example .env        # macOS/Linux: cp .env.example .env
# edit .env (only KRAKEN_API_KEY / SECRET if you go beyond dry_run)
# config.yaml is already provided (mirrors config.example.yaml)

# 3. Install Kraken CLI (only required for paper/live modes)
# macOS / Linux:
#   curl --proto '=https' --tlsv1.2 -LsSf \
#     https://github.com/krakenfx/kraken-cli/releases/latest/download/kraken-cli-installer.sh | sh
# Windows: grab the latest release binary from
#   https://github.com/krakenfx/kraken-cli/releases
```

## Run commands

```powershell
# Probe the CLI (and run a safe read-only sample call):
python scripts/check_kraken_cli.py

# Real xStocks probe (read-only — 4 calls × N symbols):
python scripts/probe_xstocks.py

# Rank xStocks by opportunity score (writes data/xstocks_rank_*.json+csv):
python scripts/rank_xstocks.py --top 5

# Paper smoke test (read-only by default; --init / --place-test-order are opt-in):
python scripts/paper_smoke_test.py

# Run exactly one full cycle and print a summary:
python scripts/dry_run_once.py

# Analyse a paper / dry-run session (Markdown + JSON in data/):
python scripts/analyze_paper_run.py --since 24

# Continuous loop (Ctrl+C to stop):
python scripts/run_agent_loop.py

# Dashboard (http://127.0.0.1:8000):
uvicorn src.dashboard.app:app --reload

# Run the test suite:
pytest

# Build an audit bundle into export/<timestamp>/:
python scripts/export_audit_bundle.py
```

## Safety

- **Default mode is `dry_run`.** Live trading requires all three of:
  - `TRADING_MODE=live`
  - `LIVE_TRADING=true`
  - `ALLOW_LIVE_ORDERS=true`
- The risk manager re-validates the triple gate at every cycle. A dedicated
  test (`tests/test_risk.py`) iterates over every partial combination of the
  three flags and proves that the order is blocked unless all three are set.
- **Use a Kraken API key with the minimum scope.** For the hackathon audit
  this means **read-only**: no order placement, **no withdrawal**, no
  margin/futures permissions. The full-trading key (if any) should be a
  separate, locally-stored key that is never committed.
- Secrets are masked in logs by `src/logger.py` (regex + env-value
  comparison).
- The Kraken CLI ships a dead-man's switch
  (`kraken order cancel-after <seconds>`); call it from your own runner
  before going live.
- Locally computed PnL is labelled `source = "local_estimate"`. The
  official, audit-grade PnL comes from Kraken via the read-only key.

## Submission notes

- The Kraken track is scored purely on **net PnL** (realized + unrealized) over
  the competition window, audited by Kraken via a read-only API key
  submitted by the participant. This project never asks Kraken to grant
  withdrawal permission and **never executes a live order during the build**.
- `scripts/export_audit_bundle.py` writes a self-contained dump of decisions,
  orders, PnL snapshots and the configuration (with all secrets redacted) for
  the GitHub submission / demo video.

### Submission readiness

| Stage              | Recommended mode | Why                                                                                |
|--------------------|------------------|------------------------------------------------------------------------------------|
| Demo video         | `dry_run`        | Deterministic logs, no external dependency, surfaces the full decision pipeline.   |
| Calibration        | `paper`          | Real CLI feedback, real PnL accounting on a paper account — no real money at risk. |
| Race / live audit  | `live`           | **Only** after user audit + read-only Kraken key configured + triple opt-in.       |

Final checklist before submission:

- [ ] `pytest` is green locally.
- [ ] `python scripts/probe_xstocks.py` runs against the real Kraken CLI (WSL ok).
- [ ] `python scripts/paper_smoke_test.py` confirms paper init status.
- [ ] `python scripts/rank_xstocks.py --top 5` writes a fresh ranking.
- [ ] `python scripts/analyze_paper_run.py --since 24` produces a Markdown
      report you are happy to publish.
- [ ] `python scripts/export_audit_bundle.py` packs decisions/orders/PnL/config
      (secrets redacted) for the GitHub submission / demo video.

## Roadmap

- Confirm the exact xStocks pair-symbol form accepted by `kraken ticker` and
  remove the slash/compact retry loop (`TODO: confirm`).
- Wire `kraken order cancel-after` into `scripts/run_agent_loop.py` once live
  mode is genuinely enabled.
- Replace the rule-based regime classifier with a calibrated logistic
  regression over recent returns / realised vol / Amihud illiquidity.
- Add a portfolio rebalancer that targets equal-risk contribution across the
  approved active positions.

## Kraken CLI status

Validated against `kraken 0.3.2` on 2026-05-14 — full report:
[`CLI_VALIDATION.md`](./CLI_VALIDATION.md). **52/52 read-only calls
succeeded; 0 orders placed.**

| Command                                                              | Status       |
|----------------------------------------------------------------------|--------------|
| `kraken status -o json`                                              | Confirmed    |
| `kraken ticker <pair> --asset-class tokenized_asset -o json`         | Confirmed    |
| `kraken ohlc <pair> --interval 60 --asset-class tokenized_asset -o json` | Confirmed |
| `kraken orderbook <pair> --count <n> --asset-class tokenized_asset -o json` | Confirmed |
| `kraken trades <pair> --count <n> --asset-class tokenized_asset -o json` | Confirmed |
| `kraken paper init/reset/buy/sell/status/balance/history/orders -o json` | Available; only `status` exercised (no order placed) |
| `kraken order buy/sell <pair> <vol> --type <t> [--price] --asset-class tokenized_asset --validate` | Confirmed (help only) |
| `kraken order cancel-after <s>`                                      | Documented (not exercised) |
| xStocks symbol form `TICKERx/USD`                                    | **Confirmed** (slash form) |

### Transport selection

`src/kraken_cli.py` invokes the CLI through one of three transports,
auto-detected at runtime:

| `KRAKEN_CLI_TRANSPORT` | Behaviour                                                                 |
|------------------------|---------------------------------------------------------------------------|
| `auto` (default)       | Try native Windows binary first, then `wsl -- bash -lc "kraken ..."`, else mock. |
| `windows`              | Force the Windows binary on PATH; mock if absent.                         |
| `wsl`                  | Force the binary inside the default WSL distro; mock if absent.           |
| `mock`                 | Use the deterministic mock generator (useful in CI / tests).              |

On Windows the official installer doesn't ship a native binary today, so
install via WSL (see `CLI_VALIDATION.md` §8).

## License

MIT. See `pyproject.toml`.
