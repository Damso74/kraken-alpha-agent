# Research runs V2 — RUN_LOG

**Date (UTC):** 2026-05-19  
**Agent:** Phase 6 — research runs V2 (Agent 15)  
**Environment:** Windows 11, PowerShell, `.\.venv\Scripts\Activate.ps1`, `$env:PYTHONIOENCODING='utf-8'` (demo only)

## Script fixes applied (minimal, `scripts/` only)

| File | Fix |
|------|-----|
| `scripts/event_study_stablecoins.py` | Wire `fetch_daily_ohlc_from_args(args)` (respects `--ohlc-source`) |
| `scripts/event_study_wikipedia.py` | Same |
| `scripts/event_study_calendar.py` | Same |
| `scripts/event_study_exchange_status.py` | Same |
| `scripts/event_study_eth_gas.py` | Same |
| `scripts/event_study_deribit_expiry.py` | Same |

No `config.yaml` or profile changes. No fabricated data.

---

## Priority 1

### 1. Stablecoin supply expansion (`stablecoins_365d`)

```powershell
python scripts/event_study_stablecoins.py --days 365 --ohlc-source binance-public --output-json reports/research_runs_v2/stablecoins_365d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** |
| Duration | ~7 s |
| APIs | DefiLlama stablecoin supply (cache), Binance `/api/v3/klines` BTCUSDT 1d (200) |
| OHLC | **371** daily candles via `binance-public` (cached to `data/collector_cache/ohlc_daily_BTC.json`) |
| Events | **0** aligned (366 supply rows; z≥1.5, lookback 180, direction=high) |
| BH @ FDR 0.05 | 0/0 cells |
| Script verdict | `blocked: insufficient events` |
| **Research verdict** | **blocked** — zero events at default z=1.5; not weak evidence |

**Z-threshold probe (documented, not shipped as primary artifact):**

```powershell
python scripts/event_study_stablecoins.py --days 365 --z-threshold 1.0 --ohlc-source binance-public
```

At z=1.0: **12** events, BH **1/5** rejects (return post_7 raw p≈0.01). Hypothesis becomes testable only after lowering z — still not promoted without pre-registration.

**Artifact:** `reports/research_runs_v2/stablecoins_365d.json`

---

### 2. Wikipedia attention (`wikipedia_365d`)

```powershell
python scripts/event_study_wikipedia.py --days 365 --ohlc-source binance-public --output-json reports/research_runs_v2/wikipedia_365d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** |
| Duration | ~10 s |
| APIs | Wikimedia pageviews REST (200, compliant User-Agent), Binance OHLC (cache hit) |
| Pageviews | **365** rows (`Bitcoin`, `en.wikipedia`) |
| Events | **16** aligned (momentum z≥2.0, lookback 30) |
| BH @ FDR 0.05 | **0/5** reject (Phase 3 had 1/5 on Kraken OHLC — FDR borderline) |
| Best raw p | realized_vol post_3 p≈0.020 |
| Script verdict | `weak evidence` |
| **Research verdict** | **weak evidence** — raw p<0.05 but BH rejects nothing |

**Artifact:** `reports/research_runs_v2/wikipedia_365d.json`

---

### 3. Calendar weekend start (`calendar_730d`)

```powershell
python scripts/event_study_calendar.py --days 730 --ohlc-source binance-public --output-json reports/research_runs_v2/calendar_730d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** |
| Duration | ~13 s |
| APIs | Binance OHLC only (calendar is deterministic) |
| Events | **105** (weekend_start), **736** daily candles |
| BH @ FDR 0.05 | **0/5** reject H0 |
| Script verdict | `not supported, move on` |
| **Research verdict** | **not supported, move on** |

**Artifact:** `reports/research_runs_v2/calendar_730d.json`

---

## Priority 2

### 4. Exchange status incidents (`exchange_status_365d`)

```powershell
python scripts/event_study_exchange_status.py --days 365 --ohlc-source binance-public --output-json reports/research_runs_v2/exchange_status_365d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** |
| Duration | ~9 s |
| APIs | Status pages (cache), Binance OHLC (cache hit) |
| Events | **2** (impact≥major, all venues) |
| BH @ FDR 0.05 | **0/5** |
| Script verdict | `weak evidence` |
| **Research verdict** | **weak evidence** — n<5, underpowered |

**Artifact:** `reports/research_runs_v2/exchange_status_365d.json`

---

### 5. Fear & Greed demo (`demo_fng_365d`)

```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts/demo_event_study.py --days 365 --json-out reports/research_runs_v2/demo_fng_365d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** (requires UTF-8 stdout on Windows — cp1252 crashes on `→`) |
| Duration | ~8 s |
| APIs | alternative.me F&G (cache), Kraken public OHLC (demo harness still uses Kraken) |
| Events | **129** (F&G < 25) |
| BH @ FDR 0.05 | **2/5** reject (realized_vol post_3/post_7) |
| Script verdict | informational BH-survival message |
| **Research verdict** | **weak evidence** — demo harness only; return hypothesis not supported |

**Note:** Demo OHLC not migrated to `--ohlc-source`; out of scope for minimal fix.

**Artifact:** `reports/research_runs_v2/demo_fng_365d.json`

---

### 6. ETH gas congestion — **skipped (blocked)**

| Field | Value |
|-------|-------|
| History cache | **absent** (`data/collector_cache/etherscan_gas_history.json`) |
| Required rows | ≥181 (lookback=180) |
| **Research verdict** | **blocked** — no real history cache |

**Unblock:** set `ETHERSCAN_API_KEY`, daily-append or seed `etherscan_gas_history.json` per `data/collector_cache/README.md`.

---

## Summary

| Signal | Events | BH rejected | Verdict |
|--------|--------|-------------|---------|
| stablecoin_supply_z_high | 0 | — | blocked |
| wikipedia_btc_attention | 16 | 0/5 | weak evidence |
| calendar_weekend_start | 105 | 0/5 | not supported, move on |
| exchange_status_major_incident | 2 | 0/5 | weak evidence |
| demo_fear_greed_extreme_fear | 129 | 2/5 | weak evidence |
| eth_gas_congestion | — | — | blocked |

**OOS candidates:** 0  
**Tradable / live-ready:** 0

Rebuild leaderboard: `python reports/_build_leaderboard.py --v2`
