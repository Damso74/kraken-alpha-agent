# VPS runbook — Kraken Alpha Agent (xStocks)

This runbook is intentionally short. Read it once before flipping the
triple opt-in for live trading on a remote VPS. Every step is
copy/paste-friendly and assumes a clean Ubuntu 24.04 LTS box.

> The agent is **safe-by-default**. Live trading requires three env
> flags simultaneously (`TRADING_MODE=live`, `LIVE_TRADING=true`,
> `ALLOW_LIVE_ORDERS=true`) AND the `micro_live_100eur` profile AND
> the `--validate` xStocks check to have produced at least one OK
> symbol. The included scripts refuse to start without all of them.

---

## 1. Provision

- **OS**: Ubuntu 24.04 LTS (the Kraken CLI installer supports it).
- **CPU / RAM**: 1 vCPU / 1 GB RAM is enough for the agent loop and
  dashboard. SSD-backed storage strongly preferred (SQLite WAL).
- **Network**: outbound HTTPS to `api.kraken.com` is sufficient. No
  inbound port is required.
- **User**: create a dedicated unprivileged user, e.g. `agent`:

```bash
sudo adduser --disabled-password --gecos "" agent
sudo usermod -aG sudo agent
sudo su - agent
```

---

## 2. Install Kraken CLI

The official Kraken CLI 0.3.2 ships with an installer:

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates python3-venv python3-pip tmux git unzip
curl -fsSL https://github.com/krakenfx/kraken-cli/releases/latest/download/install.sh | bash
kraken --version    # should print 0.3.2 or newer
```

> No paper init is needed for xStocks — the paper engine cannot route
> `tokenized_asset` orders (`--asset-class` rejected on `paper buy/sell`,
> see AGENTS.md). The agent loop simulates paper fills locally.

---

## 3. Clone the agent

```bash
cd ~
git clone https://github.com/Damso74/kraken-alpha-agent.git
cd kraken-alpha-agent
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

---

## 4. Environment file

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` (using `nano`/`vim`). Populate the two Kraken keys (the
read-only key is fine for shadow mode and validate; live trading needs
a key with **Order Place** permission only — NEVER withdrawal):

```ini
TRADING_MODE=dry_run        # flip to "live" only on the live tmux pane
LIVE_TRADING=false          # flip to "true" only on the live tmux pane
ALLOW_LIVE_ORDERS=false     # flip to "true" only on the live tmux pane
KRAKEN_API_KEY=…            # never log or commit (spot read-only is fine for shadow)
KRAKEN_API_SECRET=…         # never log or commit
KRAKEN_FUTURES_API_KEY=…    # required for the futures engine (micro_live_100eur)
KRAKEN_FUTURES_API_SECRET=…
KRAKEN_ALPHA_PROFILE=aggressive_competition   # shadow default (engine: spot)
```

`.env` is in `.gitignore`. Verify it: `git status` must show *no* `.env`.

### Setting up the Kraken Futures API key (one-time)

The futures venue is **separate** from spot on Kraken — credentials are
issued from https://futures.kraken.com (not the main `kraken.com` account
page). Create a dedicated key for the agent with the following
permissions:

| Permission        | Setting   |
|-------------------|-----------|
| Read account      | ENABLE    |
| Place orders      | ENABLE    |
| Cancel orders     | ENABLE    |
| Withdraw funds    | **DISABLE** (the agent never withdraws) |
| Transfer funds    | **DISABLE** |
| IP allow-list     | restrict to the VPS public IP if possible |

Once the key is created, store it in the VPS `.env` (`chmod 600 .env`).
The agent reads `KRAKEN_FUTURES_API_KEY` / `KRAKEN_FUTURES_API_SECRET`
first; it falls back to the spot keys only if the dedicated futures keys
are missing.

### Setting the persistent leverage preference (one-time, futures only)

`kraken futures order buy` does not expose `--leverage`; the venue uses a
per-symbol persistent preference set via `kraken futures set-leverage`.
Set every xStocks Perp the agent might trade to **1x**:

```bash
for sym in PF_AAPLXUSD PF_NVDAXUSD PF_TSLAXUSD PF_GOOGLXUSD \
           PF_SPYXUSD PF_QQQXUSD PF_MSTRXUSD PF_CRCLXUSD \
           PF_HOODXUSD PF_GLDXUSD; do
  kraken futures set-leverage "$sym" 1 -o json
done
kraken futures leverage -o json | jq    # confirm every preference is 1
```

---

## 5. Shadow run (no live orders)

Open a tmux session and run the agent in `dry_run` mode against the
real Kraken CLI:

```bash
tmux new -s shadow
cd ~/kraken-alpha-agent
. .venv/bin/activate
export KRAKEN_ALPHA_PROFILE=aggressive_competition
export TRADING_MODE=dry_run
python scripts/dry_run_once.py        # smoke test
python scripts/run_agent_loop.py      # continuous loop
# detach with Ctrl-b d
```

Or use the helper: `bash scripts/run_vps_shadow.sh` (see mission 8).

The dashboard can be exposed locally with `uvicorn` if you want it; do
NOT bind it to a public interface without auth.

---

## 6. Validate-only xStocks check

Before flipping live, prove the Kraken endpoint accepts our xStocks
orders. **The active engine determines which validate script runs**:

### 6a. Spot engine (`aggressive_competition` profile)

```bash
. .venv/bin/activate
python scripts/validate_live_xstocks.py
# writes data/validate_live_xstocks_<ts>.json
# writes data/validate_live_xstocks_latest.json
```

The script ONLY ever calls `kraken order ... --validate` on the spot
venue. At least one symbol must come back OK.

### 6b. Futures engine (`micro_live_100eur` profile — the live target)

`kraken futures order buy` has **no** `--validate` flag on `kraken 0.3.2`,
so the validate fallback uses `kraken futures paper buy <PF_xxx>` — the
futures paper engine is auth-gated, uses real market data and **cannot**
touch mainnet collateral:

```bash
. .venv/bin/activate
python scripts/validate_live_xstocks_perps.py
# writes data/validate_live_xstocks_perps_<ts>.json
# writes data/validate_live_xstocks_perps_latest.json
```

At least one symbol must come back OK. The script forces `--leverage 1`
on every call.

---

## 7. Preflight

```bash
python scripts/live_preflight.py
# expects KRAKEN_ALPHA_PROFILE=micro_live_100eur for the live host
```

The preflight refuses to pass if:
- API keys are missing.
- The engine-specific validate artefact is missing or all FAIL
  (`validate_live_xstocks_latest.json` for `engine: spot`,
  `validate_live_xstocks_perps_latest.json` for `engine: futures`).
- `micro_live_100eur` is not the active profile.
- Shorting is enabled.
- `max_total_exposure_usd` > 30 or `max_position_notional_usd` > 10.
- `LOW_LIQUIDITY` is missing from `risk.block_if_regime`.
- `src/exit_rules.py` does not import cleanly.
- **Futures engine specifics** (only when `engine: futures`):
  - `KRAKEN_FUTURES_API_KEY` / `_SECRET` (or the spot fallbacks) are
    missing (`futures_keys_present` check).
  - `execution.engine` is not `futures` (`futures_engine_active`).
  - `futures.max_leverage` differs from 1.0 or
    `src.risk.HARDCODED_MAX_LEVERAGE` is not 1.0 (`max_leverage_eq_1`).
  - `futures.max_funding_rate_pct_per_hour` is `<= 0` or `> 5`
    (`funding_rate_threshold_set`).

---

## 8. Live micro session

Switch to a **second** tmux window so shadow keeps running:

```bash
tmux new -s live
cd ~/kraken-alpha-agent
. .venv/bin/activate

# Activate the live profile + triple opt-in IN THIS SHELL ONLY.
export KRAKEN_ALPHA_PROFILE=micro_live_100eur
export TRADING_MODE=live
export LIVE_TRADING=true
export ALLOW_LIVE_ORDERS=true

# Re-run the preflight from this shell to make sure the env is correct.
python scripts/live_preflight.py --allow-live-env-check

# Start the loop (or use scripts/run_vps_micro_live.sh which adds a
# dead-man's switch via `kraken order cancel-after 60`).
python scripts/run_agent_loop.py
```

### End-of-Friday rule

Stop trading before the US_CORE close on Friday. The agent's
`flatten_before_close_exit` rule will trigger 15 minutes before
16:00 ET on every weekday — but on Friday you MUST also kill the loop:

```bash
# from the live tmux window
Ctrl-c            # graceful stop after the next cycle
```

Then double-check on Kraken that no open xStocks position remains
across the weekend.

---

## 9. Security checklist

- API key has **NO withdrawal permission**. Verify in Kraken
  settings, not in code.
- `.env` is owned by `agent` only: `chmod 600 .env`.
- No secret is ever printed by the agent (regex masker in
  `src/logger.py`; tests assert this).
- Disable SSH password auth on the VPS; use only key-based login.
- Keep `KRAKEN_API_KEY` / `KRAKEN_API_SECRET` out of git history
  (this repo's `.gitignore` already covers `.env*`).
- The agent never funds, withdraws, or moves cash between accounts.

If anything looks wrong: kill both tmux windows and revert
`KRAKEN_ALPHA_PROFILE=aggressive_competition` + the triple opt-in to
false. Live mode is single-toggle reversible.
