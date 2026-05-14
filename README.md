# Kraken Alpha Agent · Kraken Sentinel

> Autonomous xStocks trading agent built on the
> [Kraken CLI](https://www.kraken.com/kraken-cli) for the
> **AI Agent Olympics — Kraken Trading Performance** track.

**Public alias:** `Kraken Sentinel` · **Codename:** `Kraken Alpha Agent`

---

## Disclaimer

This project is for **hackathon and educational purposes only**. It is **not
financial advice**. Live trading involves risk. The default operating mode
is `dry_run` — no order can leave the process without an explicit triple
opt-in. See [`DISCLAIMER.md`](./DISCLAIMER.md) for the full text.

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
┌─────────────────────────────────────────────────────────────────────────┐
│ market_data ──> features ──> regime ──> strategies ──> ensemble ──> risk│
│                                                              │           │
│                                                              ▼           │
│                                          dry_run / paper / live  (CLI)   │
│                                                              │           │
│                                              persist ────────┴──> dashboard
└─────────────────────────────────────────────────────────────────────────┘
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
| Risk             | `src/risk.py`                | Single gate for any order — incl. live triple opt-in           |
| Execution        | `src/execution.py`           | `dry_run` / `paper` / `live` execution router                  |
| Portfolio + PnL  | `src/portfolio.py`, `pnl.py` | Local-estimate bookkeeping (clearly labelled)                  |
| LLM explainer    | `src/llm_explainer.py`       | Optional Featherless explanation (JSON only)                   |
| Storage          | `src/storage.py`             | SQLite (6 tables) + JSONL writers                              |
| Dashboard        | `src/dashboard/`             | FastAPI + Jinja2 trading-terminal style                        |
| Orchestrator     | `src/main.py`                | `run_one_cycle` / `run_loop`                                   |

## Strategy

- **Momentum** — leans on short-horizon returns (5m, 15m, 1h) with a saturating tanh-like
  squash. Strong moves score close to ±1.
- **Breakout** — proximity to the 1h high/low. Buys near the 1h high, sells near the
  1h low.
- **Mean reversion** — fades sharp 15m moves that do not match the 1h direction.
- **Ensemble** —
  ```
  final_score = 0.40 * momentum
              + 0.25 * breakout
              + 0.20 * mean_reversion
              - 0.10 * volatility_penalty
              - 0.05 * spread_penalty
  ```
  Action is `BUY` above `+0.35`, `SELL` below `-0.35`, otherwise `HOLD`.

## Modes

| Mode      | Behaviour                                                                                                          |
|-----------|--------------------------------------------------------------------------------------------------------------------|
| `dry_run` | Default. The agent logs every decision but **never** invokes a trading command.                                    |
| `paper`   | Calls `kraken paper buy/sell ...` when the CLI is installed; otherwise falls back to a clearly labelled simulation.|
| `live`    | Calls `kraken order buy/sell ...`. **Requires the full triple opt-in** (see below) and only places approved sizes. |

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

# Run exactly one full cycle and print a summary:
python scripts/dry_run_once.py

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
- Submission checklist:
  - [ ] GitHub repo public (this repo).
  - [ ] Recorded demo video — `python scripts/dry_run_once.py` followed by the
        dashboard, in under 90 seconds.
  - [ ] Read-only Kraken API key submitted to lablab.ai / Kraken organisers.

## Roadmap

- Confirm the exact xStocks pair-symbol form accepted by `kraken ticker` and
  remove the slash/compact retry loop (`TODO: confirm`).
- Wire `kraken order cancel-after` into `scripts/run_agent_loop.py` once live
  mode is genuinely enabled.
- Replace the rule-based regime classifier with a calibrated logistic
  regression over recent returns / realised vol / Amihud illiquidity.
- Add a portfolio rebalancer that targets equal-risk contribution across the
  approved active positions.

## Confirmed vs. TODO Kraken CLI commands

| Command                                          | Status       |
|--------------------------------------------------|--------------|
| `kraken ticker <pair> --output json`             | Confirmed    |
| `kraken ohlc <pair> --interval 60 --output json` | Confirmed    |
| `kraken paper init/buy/sell/reset`               | Confirmed    |
| `kraken order buy/sell`                          | Confirmed    |
| `kraken order cancel-after <seconds>`            | Confirmed    |
| `kraken <order> --validate`                      | Confirmed    |
| `kraken mcp -s all`                              | Confirmed    |
| `kraken balance`                                 | TODO confirm |
| `kraken paper status`                            | TODO confirm |
| `kraken orderbook <pair>`                        | TODO confirm |
| xStocks symbol form `TICKERx/USD` vs `TICKERxUSD`| TODO confirm |

Each TODO is isolated in `src/kraken_cli.py` with a deterministic mock
fallback so the agent runs even when the CLI is unavailable.

## License

MIT. See `pyproject.toml`.
