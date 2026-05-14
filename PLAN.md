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
- `kraken paper init` and a `paper buy/sell` round-trip remain **manual
  opt-in** only — runnable via `python scripts/paper_smoke_test.py --init`
  or `--place-test-order`. The default invocation is read-only.
- `kraken order ... --validate` against an xStock (validate-only, no money
  moves; gated by the triple opt-in for safety).

## File structure
```
src/
  main.py              Orchestrator — run_one_cycle / run_loop / resolve_universe
  config.py            Pydantic-settings, .env + config.yaml loader + load_active_profile
  schemas.py           Pydantic models for Decision/StrategyVote/Risk/...
  kraken_cli.py        Subprocess wrapper around the Kraken CLI (auto / wsl / mock)
  market_data.py       Public market data (uses wrapper, mock fallback)
  universe.py          xStocks allowlist + normalisation + build_dynamic_universe
  ranking.py           Pure RankedSymbol scorer + filters (shared by script + agent)
  features.py          Pure feature engineering
  regime.py            Market regime classifier
  strategies/          momentum / breakout / mean_reversion / ensemble (v2 + liquidity)
  risk.py              Risk manager (triple opt-in gate, per-profile rate limit)
  execution.py         Routes to dry_run / paper / live
  portfolio.py         Balances + positions + history
  pnl.py               Realized / unrealized / net (local_estimate)
  llm_explainer.py     Optional Featherless explanation
  storage.py           SQLite + JSONL writers
  logger.py            Structured logs with secret masking
  utils.py             Misc helpers
  dashboard/           FastAPI + Jinja templates (profile banner, /ranking)
scripts/
  check_kraken_cli.py  Installation probe
  probe_xstocks.py     Read-only CLI validation probe
  rank_xstocks.py      Real-data ranking pass (JSON + CSV)
  paper_smoke_test.py  Paper status / balance / orders / history; opt-in --init / --place-test-order
  dry_run_once.py      Single dry-run cycle
  run_agent_loop.py    Continuous loop
  export_audit_bundle.py
tests/
  test_features.py / test_regime.py / test_strategies.py
  test_risk.py (proves live-trading triple gate)
  test_decision_schema.py / test_storage.py
  test_kraken_cli_wrapper.py
  test_ranking.py / test_universe_dynamic.py
  test_profiles.py / test_risk_aggressive.py / test_paper_smoke.py
data/                  SQLite + JSONL + rank JSON/CSV (gitignored)
```

## Implementation status
1. ✅ Scaffolding (config, schemas, storage, logger).
2. ✅ Deterministic engine (features → regime → strategies → ensemble → risk).
3. ✅ Kraken CLI wrapper with mock + WSL fallbacks.
4. ✅ `scripts/dry_run_once.py` end-to-end.
5. ✅ Portfolio / PnL (`local_estimate`).
6. ✅ Execution module with triple opt-in.
7. ✅ Optional Featherless LLM explainer.
8. ✅ FastAPI dashboard.
9. ✅ Tests + scripts + README/DISCLAIMER.
10. ✅ **Kraken CLI validation** (`CLI_VALIDATION.md`, 52/52 read-only calls OK).
11. ✅ **Competition mode** — ranking, dynamic universe, profiles, ensemble v2,
    dashboard competition view, paper smoke test (read-only by default).

## Competition mode

- `src/ranking.py` exposes `compute_symbol_rank` / `apply_filters` /
  `select_top_n` as pure functions, shared by `scripts/rank_xstocks.py` and
  by the runtime's dynamic universe selector.
- `config.yaml` carries three profiles (`balanced`, `aggressive_competition`,
  `conservative_debug`) that deep-merge over the base config via
  `load_active_profile`. The active profile can also be overridden by the
  `KRAKEN_ALPHA_PROFILE` environment variable.
- `universe.mode: dynamic` runs a ranking pass each cycle and keeps the
  top-N opportunities (defaults: spread ≤ 80 bps, volume ≥ 100,
  trade_count ≥ 10, top_n = 8).
- The risk manager now enforces `max_trades_per_hour`, `stop_loss_pct` and
  `take_profit_pct` from the active profile. Live opt-in remains universal.
- The dashboard reads `data/xstocks_rank_latest.json` (60 s cache) and
  surfaces a ranking section plus profile / PnL-source / paper banners.
  `/ranking` returns the raw JSON.

## Roadmap (post-hackathon)
- One-time manual `kraken paper init` to unlock paper trading round-trips.
- Wire `kraken order cancel-after` into `scripts/run_agent_loop.py`.
- Replace the rule-based regime classifier with a calibrated logistic
  regression over recent returns / realised vol / Amihud illiquidity.
- Add a portfolio rebalancer that targets equal-risk contribution across
  the approved active positions.

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
