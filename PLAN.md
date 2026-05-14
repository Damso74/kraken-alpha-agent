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

## Confirmed Kraken CLI commands (from tutorial + official site)
- `kraken ticker <pair> --output json`
- `kraken ohlc <pair> --interval 60 --output json`
- `kraken paper init --balance <n> --currency <ccy>`
- `kraken paper buy <pair> <volume> --yes`
- `kraken paper sell <pair> <volume> --yes`
- `kraken paper reset --balance <n> --currency <ccy> --yes`
- `kraken order buy|sell ...` (live)
- `kraken order cancel-after <seconds>` (dead-man's switch)
- `kraken <order-cmd> --validate` (live simulation, no order placed)
- `kraken mcp -s all` (MCP server)
- Global output flag: `--output json` (also documented as `-o json`)
- Public market data needs no API keys.

## Commands marked TODO (not 100% confirmed by primary sources)
- `kraken balance` / `kraken account balance` — wrapper falls back to mock with TODO.
- `kraken trades history` — wrapper falls back to mock with TODO.
- `kraken orderbook <pair>` — wrapper falls back to mock with TODO.
- `kraken paper status` (referenced in tutorial dashboard) — wrapper falls back to mock with TODO.
- xStocks pair format on the CLI (`TSLAx/USD` vs `TSLAxUSD`). Normalisation
  helper tries both and reports the first one accepted; default form is
  `<TICKERx>/USD`.
- Tested via `--validate` before any real exposure.

These are all isolated behind `kraken_cli.py`; nothing breaks if a command is
renamed: the wrapper returns a deterministic mock and logs a TODO.

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
