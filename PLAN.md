# Kraken Alpha Agent — Plan

## Mission
Autonomous trading agent for **xStocks** on Kraken using the **Kraken CLI** as the
execution layer. Optimised for **net PnL** (realized + unrealized). Auditable
through Kraken read-only API key. Dashboard + dry-run by default.

Track: AI Agent Olympics — Kraken Trading Performance.

## Sources consulted
- https://github.com/krakenfx/kraken-cli (repo overview)
- https://www.kraken.com/kraken-cli (commands surface & safety guarantees)
- https://lablab.ai/ai-tutorials/featherless-kraken-multi-model-financial-agent (working code examples)
- https://support.kraken.com/articles/xstocks-faq
- https://support.kraken.com/articles/getting-started-with-xstocks
- https://docs.kraken.com/api/docs/rest-api/get-ticker-information/
- https://featherless.ai/docs/api-examples-and-snippets
- https://lablab.ai/ai-hackathons/milan-ai-week-hackathon

## Confirmed Kraken CLI commands (validated against `kraken 0.3.2`)

See [`CLI_VALIDATION.md`](./CLI_VALIDATION.md) for the full validation log.

- `kraken status -o json` — system status.
- `kraken ticker <pair> --asset-class tokenized_asset -o json` — required flag for xStocks.
- `kraken ohlc <pair> --interval 60 --asset-class tokenized_asset -o json`.
- `kraken orderbook <pair> --count <n> --asset-class tokenized_asset -o json` (note `--count`, not `--depth`).
- `kraken trades <pair> --count <n> --asset-class tokenized_asset -o json`.
- `kraken paper init/reset/buy/sell/status/balance/history` — paper engine is
  local and never sends real orders. Only `status` was exercised during
  validation.
- `kraken order buy|sell <pair> <vol> --type <t> [--price ...] --asset-class tokenized_asset --validate` — confirmed via `--help`; no real order placed.
- `kraken order cancel-after <s>` — dead-man's switch (documented, not exercised).
- Global output flag: `-o json` (equivalent to `--output json`).

### Confirmed xStocks pair format

Slash form, e.g. `AAPLx/USD`, `TSLAx/USD`, `NVDAx/USD`. The wrapper still
retries the compact form (`AAPLxUSD`) defensively.

### Transport

On Windows the official installer does not ship a native binary, so the
wrapper invokes `kraken` through WSL: `wsl -- bash -lc "kraken ..."`. The
transport is controllable via `KRAKEN_CLI_TRANSPORT=auto|windows|wsl|mock`.

## Items still mocked / not exercised

- Authenticated `kraken balance` (requires a read-only API key on the host).
- `kraken paper init` and a `paper buy/sell` round-trip (we deliberately did
  not initialise a paper account during validation — the wrapper still
  produces clearly-labelled simulated fills until `paper init` is run).
- `kraken order ... --validate` against an xStock (validate-only, no money
  moves; gated by the triple opt-in for safety).

## File structure
```
src/
  main.py              CLI entrypoint (not required for v1)
  config.py            Pydantic-settings, .env + config.yaml loader
  schemas.py           Pydantic models for Decision/StrategyVote/Risk/...
  kraken_cli.py        Subprocess wrapper around the Kraken CLI
  market_data.py       Public market data (uses wrapper, mock fallback)
  universe.py          xStocks allowlist + normalisation
  features.py          Pure feature engineering
  regime.py            Market regime classifier
  strategies/          momentum / breakout / mean_reversion / ensemble
  risk.py              Risk manager (triple opt-in gate)
  execution.py         Routes to dry_run / paper / live
  portfolio.py         Balances + positions + history
  pnl.py               Realized / unrealized / net (local_estimate)
  llm_explainer.py     Optional Featherless explanation
  storage.py           SQLite + JSONL writers
  logger.py            Structured logs with secret masking
  utils.py             Misc helpers
  dashboard/           FastAPI + Jinja templates
scripts/
  check_kraken_cli.py  Installation probe
  dry_run_once.py      Single dry-run cycle
  run_agent_loop.py    Continuous loop
  export_audit_bundle.py
tests/
  test_features.py / test_regime.py / test_strategies.py
  test_risk.py (proves live-trading triple gate)
  test_decision_schema.py / test_storage.py
data/                  SQLite + JSONL (gitignored)
```

## Implementation order
1. Scaffolding (config, schemas, storage, logger).
2. Deterministic engine (features → regime → strategies → ensemble → risk).
3. Kraken CLI wrapper with mock fallback.
4. `scripts/dry_run_once.py` end-to-end.
5. Portfolio / PnL.
6. Execution module with triple opt-in.
7. Optional Featherless LLM explainer.
8. FastAPI dashboard.
9. Tests + scripts + README/DISCLAIMER.

## Risks
- Kraken CLI not installed in this build → mock fallback is mandatory.
- xStocks CLI symbol normalisation unconfirmed → try both forms, log result.
- Featherless paid plans / model availability — explainer is optional.
- Live trading is intentionally hard to enable (triple opt-in).

## Safety posture
- Default mode: `dry_run` — no order ever leaves the process.
- Live requires `TRADING_MODE=live`, `LIVE_TRADING=true`,
  `ALLOW_LIVE_ORDERS=true` simultaneously.
- Secrets never logged: regex-based masker in `logger.py`.
- Kraken read-only API key for hackathon audit. **No withdrawal scope.**
