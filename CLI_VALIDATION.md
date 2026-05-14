# Kraken CLI validation report

| Field | Value |
|-------|-------|
| Validation date | 2026-05-14, ~23:13 UTC |
| Host OS | Windows 11 Famille (PowerShell) |
| Transport used | `wsl` (Ubuntu, WSL2 kernel 5.15) |
| Kraken CLI version | `kraken 0.3.2` |
| Install path | `/home/<user>/.cargo/bin/kraken` |
| Install command | Official Kraken installer inside WSL: `curl --proto '=https' --tlsv1.2 -LsSf https://github.com/krakenfx/kraken-cli/releases/latest/download/kraken-cli-installer.sh \| sh` |
| Auth used | **None.** Only public read-only endpoints. |
| Orders placed | **None.** Not even `--validate`. |

The Windows-native binary is not shipped by the official installer, so the
agent invokes the CLI through WSL when running on Windows
(`wsl -- bash -lc "kraken ..."`). The transport is configurable via the
`KRAKEN_CLI_TRANSPORT` environment variable (`auto` | `windows` | `wsl` |
`mock`).

## 1. xStocks pair format

**Confirmed.** The Kraken CLI accepts the slash form for every xStock we
tested (`AAPLx/USD`, `TSLAx/USD`, `NVDAx/USD`, `SPYx/USD`, …). All four
read-only subcommands require `--asset-class tokenized_asset` for xStocks —
without it, the CLI rejects the call with a validation error.

The compact form (`AAPLxUSD`, no slash) is **not** required in practice. The
wrapper still tries it as a defensive fallback.

## 2. Read-only command surface — confirmed against `kraken 0.3.2`

All commands tested with `KRAKEN_CLI_TRANSPORT=auto` (auto-detected as `wsl`).

| Command | Sample call | Symbols probed | Result | Median latency |
|---------|-------------|----------------|--------|----------------|
| `status` | `kraken status -o json` | — | `{"status":"online"}` | ~250 ms |
| `ticker` | `kraken ticker AAPLx/USD --asset-class tokenized_asset -o json` | all 13 xStocks | 13/13 OK | ~640 ms |
| `ohlc` | `kraken ohlc AAPLx/USD --interval 60 --asset-class tokenized_asset -o json` | all 13 xStocks | 13/13 OK | ~660 ms |
| `orderbook` | `kraken orderbook AAPLx/USD --count 10 --asset-class tokenized_asset -o json` | all 13 xStocks | 13/13 OK | ~650 ms |
| `trades` | `kraken trades AAPLx/USD --count 20 --asset-class tokenized_asset -o json` | all 13 xStocks | 13/13 OK | ~640 ms |

**Total: 52 read-only CLI calls, 52 successes, 0 failures, 0 mock fallbacks.**

The raw probe dump is saved (and ignored by git) at:
`data/probe_xstocks_<UTC>.json`.

### Field shapes (truncated examples, no secrets)

`ticker` response:
```json
{
  "AAPLx/USD": {
    "a": ["298.29", "2", "2.000"],          // ask [price, wholeLot, lot]
    "b": ["298.25", "34", "34.000"],        // bid
    "c": ["298.29", "0.552645"],            // last trade [price, vol]
    "h": ["300.84", "300.84"],              // high [today, 24h]
    "l": ["297.31", "297.31"],              // low
    "o": "298.75",                          // open
    "p": ["298.61", "298.61"],              // VWAP
    "t": [87, 87],                          // trade count
    "v": ["169.569314", "169.569314"]       // volume
  }
}
```

`ohlc` response:
```
[timestamp, open, high, low, close, vwap, volume, count]
```

`orderbook` response: `{ "<pair>": { "asks": [[price, vol, ts], ...], "bids": [...] } }`

`trades` response: `[[price, vol, ts, "b|s", "m|l", ...], ...]`

## 3. Order command surface — confirmed (help only, no order placed)

| Flag / value | Status | Notes |
|--------------|--------|-------|
| `--validate` | confirmed | "Validate only (do not submit)" — used by `validate_live_order`. |
| `--asset-class tokenized_asset` | confirmed | Required for xStocks orders. |
| `--type market \| limit \| stop-loss-limit \| ...` | confirmed | Wrapper defaults to `market`. |
| `--yes` | confirmed | Skip interactive confirmation. |
| Default order type | `limit` | Wrapper overrides to `market` when no price is given. |

The agent **never** places a real `kraken order buy/sell`. It only invokes
`order buy/sell --validate` (in `live` mode, behind the triple opt-in) before
returning to the user — and that path is itself blocked by the risk manager
unless `TRADING_MODE=live`, `LIVE_TRADING=true`, `ALLOW_LIVE_ORDERS=true`
are all set simultaneously.

## 4. Paper trading

| Sub-command | Status |
|-------------|--------|
| `kraken paper init/reset/buy/sell/balance/status/history/orders/cancel/cancel-all` | available |
| `kraken paper status -o json` (uninitialised) | returns proper JSON error: `{"error":"validation","message":"Paper account not initialized. Run 'kraken paper init' first."}` |
| Paper accounts on xStocks | **not exercised** during validation (no `paper init` performed). |

The wrapper's `fetch_paper_status()` returns the CLI payload when the account
is initialised, and falls back to a clearly-labelled mock otherwise. The
agent's `paper` execution mode therefore keeps working even before any
`kraken paper init` is done locally: it just produces a clearly-labelled
simulated fill.

## 5. Code changes applied

- `src/kraken_cli.py`
  - Removed legacy `--depth`; orderbook now uses `--count`.
  - `_augment_args()` automatically injects `--asset-class tokenized_asset`
    for any xStocks pair on supported subcommands, and forces `-o json`.
  - Added Windows ↔ WSL transport with auto-detection and
    `KRAKEN_CLI_TRANSPORT=auto|windows|wsl|mock` override.
  - New functions: `fetch_orderbook(count=…)`, `fetch_trades(count=…)`,
    `fetch_system_status()`.
  - Standard result now carries `transport` and `using_mock`.
- `src/market_data.py`
  - `get_orderbook(count=…)`, new `get_trades(count=…)`.
- `src/universe.py`
  - New `pair_format(ticker, quote="USD")` returning the official slash form.
- `src/execution.py`
  - Unchanged contract; benefits from the new asset-class injection and the
    `--validate` flag forwarded by `validate_live_order`.
- `scripts/probe_xstocks.py` — new read-only probe (no orders, ever).
- `tests/test_kraken_cli_wrapper.py` — new tests (`subprocess.run` is mocked,
  no real network).

## 6. Verification commands

```text
pytest                                  # 58 passed
python scripts/check_kraken_cli.py      # transport=wsl, version=kraken 0.3.2
python scripts/probe_xstocks.py         # 52/52 OK
python scripts/dry_run_once.py          # 13 decisions persisted (real CLI data)
```

## 7. Remaining limitations + manual follow-ups

These items are **not** blockers; they are next-step polish for whoever takes
the agent further.

| Open question | Suggested manual command |
|--------------|---------------------------|
| Real `kraken paper init` smoke test on xStocks | `wsl -- bash -lc "kraken paper init --balance 10000 --currency USD"` then `kraken paper buy AAPLx/USD 0.01 --type market --asset-class tokenized_asset --yes` — only run when you accept the simulated fill being recorded locally. |
| `kraken order buy/sell ... --validate` smoke test for an xStock | `wsl -- bash -lc "kraken order buy AAPLx/USD 0.001 --type market --asset-class tokenized_asset --validate"` once a read-only API key is configured (validate-only call, no money moves). |
| Symbol coverage outside the allowlist | `wsl -- bash -lc "kraken pairs --asset-class tokenized_asset -o json"` to enumerate every tradable xStocks pair on the venue. |
| Authenticated `kraken balance` round-trip | Requires `KRAKEN_API_KEY`/`KRAKEN_API_SECRET` (read-only scope is fine). Tested only via the wrapper's mock fallback during this validation. |
| Dead-man's switch in live mode | `kraken order cancel-after <seconds>` — wire this into `scripts/run_agent_loop.py` if you go live. |

## 8. WSL setup notes for Windows users

1. Enable WSL (PowerShell as admin): `wsl --install -d Ubuntu`.
2. Inside the WSL shell: `curl --proto '=https' --tlsv1.2 -LsSf https://github.com/krakenfx/kraken-cli/releases/latest/download/kraken-cli-installer.sh | sh`.
3. Re-open the WSL shell (or `source ~/.cargo/env`) and confirm with `kraken --version`.
4. The agent (running from Windows PowerShell) picks the WSL binary
   automatically. Override with `setx KRAKEN_CLI_TRANSPORT auto` if needed.
