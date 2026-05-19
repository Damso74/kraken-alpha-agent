# Phase 3 vs Phase 6 — research comparison

**Generated:** 2026-05-19 (Agent 15, Phase 6 research runs V2)

This document compares the first real research batch (Phase 3, `reports/research_runs/`) with the Phase 6 re-run (`reports/research_runs_v2/`). No profitability or live-trading claims are made in either phase.

## Infrastructure delta

| Dimension | Phase 3 | Phase 6 |
|-----------|---------|---------|
| OHLC default | Kraken public REST (~720 daily cap) | `--ohlc-source binance-public` (paginated klines, cache persist) |
| Event-study wiring | `fetch_daily_ohlc(ticker, days)` — ignored `--ohlc-source` | `fetch_daily_ohlc_from_args(args)` in all `event_study_*.py` |
| Wikipedia collector | Blocked (HTTP 403, no User-Agent) → later fixed | HTTP 200 with compliant User-Agent (Agent 12) |
| ETH gas history | Blocked (0 rows) | Still blocked (no `etherscan_gas_history.json`) |
| Verdict for 0 events | `weak evidence` (Phase 3 script) | `blocked: insufficient events` (Phase 6) |

## Signal-by-signal comparison

### Stablecoin supply z-high (365d)

| | Phase 3 | Phase 6 |
|---|---------|---------|
| OHLC candles | 370 (Kraken) | 371 (Binance) |
| Supply rows | 366 | 366 |
| Events (z≥1.5) | **0** | **0** |
| BH rejected | 0/0 | 0/0 |
| Verdict | weak evidence | **blocked** |

No change in substance: the hypothesis is not exercised at default z=1.5. Phase 6 documents that lowering z to 1.0 yields 12 events (BH 1/5) — exploratory only, not the primary artifact.

### Wikipedia BTC attention (365d)

| | Phase 3 | Phase 6 |
|---|---------|---------|
| Data access | Blocked → re-run after User-Agent fix | Unblocked |
| Events | 16 | 16 |
| BH rejected | **1/5** | **0/5** |
| Best raw p | realized_vol post_3 ≈ 0.010 | realized_vol post_3 ≈ 0.020 |
| Verdict | weak evidence | weak evidence |

Phase 3 leaderboard had one BH rejection on Kraken OHLC; Phase 6 on Binance OHLC loses FDR significance (q≈0.10). Raw vol elevation persists but does not survive multiple testing — verdict unchanged at weak evidence.

### Calendar weekend start (730d)

| | Phase 3 | Phase 6 |
|---|---------|---------|
| OHLC candles | 721 (Kraken) | 736 (Binance) |
| Events | 103 | 105 |
| BH rejected | 0/5 | 0/5 |
| Verdict | not supported, move on | not supported, move on |

Longer OHLC history adds two weekend events; conclusion unchanged.

### Exchange status major incident (365d)

| | Phase 3 | Phase 6 |
|---|---------|---------|
| Events | 2 | 2 |
| BH rejected | 0/5 | 0/5 |
| Verdict | weak evidence | weak evidence |

Identical — still underpowered (n<5).

### Demo Fear & Greed (extreme fear)

| | Phase 3 (180d) | Phase 6 (365d) |
|---|----------------|----------------|
| Window | 180 days | 365 days |
| Events | 113 | 129 |
| BH rejected | 0/5 | **2/5** (vol cells) |
| Return post_7 | positive-ish, p≈0.14 | **negative** mean, p≈0.55 |
| Verdict | weak evidence | weak evidence |

Longer window increases vol-related BH rejections but the stated return hypothesis (F&G < 25 → positive forward return) is not supported. Demo remains non-promotable.

### ETH gas congestion (365d)

| | Phase 3 | Phase 6 |
|---|---------|---------|
| History rows | 0 | 0 (cache absent) |
| Run executed | exit 2 | skipped |
| Verdict | blocked | blocked |

Still requires seeding `etherscan_gas_history.json` (≥181 rows).

## Leaderboard verdict counts

| Verdict | Phase 3 | Phase 6 |
|---------|---------|---------|
| not supported, move on | 1 | 1 |
| weak evidence | 3 | 3 |
| candidate for OOS retest | 0 | 0 |
| blocked | 2 | 2 |

Phase 6 shifts stablecoins from weak evidence to **blocked** (zero events rule) and unblocks Wikipedia while keeping it at weak evidence. ETH gas remains blocked.

## What Phase 6 did not change

- No `config.yaml` edits
- No live or paper-trading profiles
- No new fabricated datasets
- No signal marked tradable, profitable, or live-ready

## References

- Phase 3 runs: `reports/research_runs/RUN_LOG.md`
- Phase 6 runs: `reports/research_runs_v2/RUN_LOG_V2.md`
- Leaderboards: `reports/ALPHA_RESEARCH_LEADERBOARD.md`, `reports/ALPHA_RESEARCH_LEADERBOARD_V2.md`
- Rebuild: `python reports/_build_leaderboard.py --all`
