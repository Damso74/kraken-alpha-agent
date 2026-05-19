# Research runs — RUN_LOG

**Date (UTC):** 2026-05-19  
**Agent:** Phase 3 — first real research runs (Agent 7)  
**Environment:** Windows 11, PowerShell, `.\.venv\Scripts\Activate.ps1`, `$env:PYTHONIOENCODING='utf-8'`

## Script fixes applied (minimal, `scripts/` only)

| File | Issue | Fix |
|------|-------|-----|
| `scripts/_event_study_common.py` | `fetch_crypto_ohlc_paginated()` called with wrong kwargs (`interval_minutes`, missing `target_candles`) | Use `interval_min=1440`, `target_candles=days+10`, positional `pair` |
| `scripts/_event_study_common.py` | `UnicodeEncodeError` on Windows cp1252 when printing `→` | `_console_text()` replaces `→` with `->` on stdout |
| `scripts/demo_event_study.py` | Same OHLC kwargs bug | Same `interval_min` / `target_candles` fix |

No `config.yaml` or profile changes. No fabricated data.

---

## Priority 1

### 1. Stablecoin supply expansion (`stablecoins_365d`)

```powershell
python scripts/event_study_stablecoins.py --days 365 --output-json reports/research_runs/stablecoins_365d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** (after OHLC fix; first attempt **1** on TypeError) |
| Duration | ~2.2 s |
| APIs | DefiLlama `stablecoins.llama.fi` (200), Kraken public OHLC (200) |
| Cache | `data/collector_cache/defillama.json` populated |
| Events | **0** aligned (366 supply rows; z≥1.5, lookback 180, direction=high) |
| BH @ FDR 0.05 | 0/0 cells (no testable cells) |
| Script verdict | `blocked: insufficient events` (aligned post merge-hygiene 4–10; was `weak evidence` at run time) |
| **Research verdict** | **blocked** — zero aligned events; hypothesis not exercised; see `research_runs_v2/stablecoins_365d.json` for Phase 6 re-run |

**Stdout (tail):**
```
[stablecoins] stablecoin supply rows: 366
[stablecoins] BTC daily OHLC: 370 candles
[stablecoins] events aligned to daily candles: 0 (0.0% of candles)
[stablecoins] VERDICT: weak evidence  # historical stdout; artifact JSON updated to blocked: insufficient events
```

**Artifact:** `reports/research_runs/stablecoins_365d.json`

---

### 2. Wikipedia attention (`wikipedia_365d`)

```powershell
python scripts/event_study_wikipedia.py --days 365 --output-json reports/research_runs/wikipedia_365d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** (re-run 2026-05-19 after User-Agent fix) |
| Duration | ~8 s |
| APIs | Wikimedia pageviews REST — **HTTP 200** (default `KrakenAlphaAgent-Research/1.0` User-Agent); Kraken OHLC **200** |
| Pageviews | **365** rows (`Bitcoin`, `en.wikipedia`) |
| Events | **16** aligned (momentum z≥2.0, lookback 30) |
| BH @ FDR 0.05 | **1/5** cells reject (realized_vol post_3) |
| Script verdict | `supported` |
| **Research verdict** | **weak evidence** — sparse shocks (n=16); vol effect may be mechanical; not tradeable without OOS |

**Fix (Phase 5 / Agent 12):** `src/data/collectors/wikimedia.py` — `wikimedia_http_get_json()` sends configurable `User-Agent` (`WIKIMEDIA_USER_AGENT` env or project default), 20 s timeout, light retry on 429/5xx. Prior failure was HTTP 403 with no User-Agent.

**Cache:** `data/collector_cache/wikimedia.json` populated on first successful fetch.

**Artifact:** `reports/research_runs/wikipedia_365d.json`

---

### 3. Calendar weekend start (`calendar_730d`)

```powershell
python scripts/event_study_calendar.py --days 730 --output-json reports/research_runs/calendar_730d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** |
| Duration | ~4.1 s |
| APIs | Kraken public OHLC only (calendar is deterministic) |
| Events | **103** (weekend_start), 721 daily candles |
| BH @ FDR 0.05 | **0/5** reject H0 |
| Best raw p | return post_7 p≈0.96; realized_vol post_3 p≈0.10 |
| Script verdict | `not supported, move on` |
| **Research verdict** | **not supported, move on** |

**Stdout (tail):**
```
[calendar] events aligned to daily candles: 103 (14.3% of candles)
[calendar] Benjamini-Hochberg at FDR=0.05: 0/5 cells reject H0
[calendar] VERDICT: not supported, move on
```

**Artifact:** `reports/research_runs/calendar_730d.json`

---

## Priority 2 (stable Priority 1 pipeline)

### 4. Exchange status incidents (`exchange_status_365d`)

```powershell
python scripts/event_study_exchange_status.py --days 365 --output-json reports/research_runs/exchange_status_365d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** |
| Duration | ~3.4 s |
| APIs | Kraken + Coinbase status pages (200), Kraken OHLC (200) |
| Cache | `data/collector_cache/status_pages.json` created |
| Events | **2** (impact≥major, all venues) — underpowered |
| BH @ FDR 0.05 | **0/5** |
| Script verdict | `weak evidence` |
| **Research verdict** | **weak evidence** (insufficient incident count for inference) |

**Artifact:** `reports/research_runs/exchange_status_365d.json`

---

### 5. ETH gas congestion (`eth_gas_365d`)

```powershell
python scripts/event_study_eth_gas.py --days 365 --output-json reports/research_runs/eth_gas_365d.json
```

| Field | Value |
|-------|-------|
| Exit code | **2** |
| Duration | ~1.6 s |
| APIs | Etherscan gas oracle — `status='0' message='NOTOK'` (no key / rate limit) |
| History rows | **0** (`data/collector_cache/etherscan_gas_history.json` absent) |
| **Research verdict** | **blocked: missing data/cache/API issue** |

**Stderr (snippet):**
```
[eth_gas] WARNING snapshot fetch failed: gas oracle error status='0' message='NOTOK'
[eth_gas] FATAL need at least 181 daily gas observations (have 0; lookback=180)
```

**Unblock:** set `ETHERSCAN_API_KEY`, run script daily to append `etherscan_gas_history.json`, or seed history per `data/collector_cache/README.md`.

**Artifact:** none

---

## Demo (optional)

### 6. Fear & Greed demo (`demo_fng_180d`)

```powershell
# Note: flag is --json-out, not --output-json
python scripts/demo_event_study.py --days 180 --json-out reports/research_runs/demo_fng_180d.json
```

| Field | Value |
|-------|-------|
| Exit code | **0** (first attempt **2** with wrong `--output-json` flag) |
| Duration | ~3.8 s |
| APIs | alternative.me FNG (200), Kraken OHLC (200) |
| Events | **113** (F&G < 25 on 185 candles — dense regime, not sparse shocks) |
| BH @ FDR 0.05 | **2/5** cells reject (return post_7, realized_vol post_7) |
| Script verdict | Custom warning (not the standard 4-string enum) |
| **Research verdict** | **weak evidence** — demo harness only; dense conditioning + single-asset window; not a claim of tradeable alpha |

**Artifact:** `reports/research_runs/demo_fng_180d.json`

---

## Summary table

| Hypothesis | Ran? | JSON | Research verdict |
|------------|------|------|------------------|
| Stablecoin supply z≥1.5 → BTC | Yes | `stablecoins_365d.json` | weak evidence (0 events) |
| Wikipedia attention → BTC | Yes | `wikipedia_365d.json` | weak evidence (n=16, vol-only BH) |
| Calendar weekend_start → BTC | Yes | `calendar_730d.json` | not supported, move on |
| Exchange status major+ → BTC | Yes | `exchange_status_365d.json` | weak evidence (n=2) |
| ETH gas congestion → BTC | **No** | — | blocked (Etherscan NOTOK + no history) |
| Demo F&G < 25 → BTC | Yes | `demo_fng_180d.json` | weak evidence (demo only) |

**Succeeded end-to-end:** 5/6 attempted (Wikimedia unblocked 2026-05-19; ETH gas still blocked).

**Caches populated this session:** `data/collector_cache/defillama.json`, `data/collector_cache/status_pages.json`, `data/collector_cache/wikimedia.json`.

---

## Next steps (not executed here)

1. ~~Add Wikimedia-compliant `User-Agent`~~ — done in `wikimedia.py` (Agent 12).
2. Seed or daily-append `etherscan_gas_history.json` with valid `ETHERSCAN_API_KEY`; re-run `event_study_eth_gas.py`.
3. Re-run stablecoins with lower `--z-threshold` or `--direction abs` if expansion shocks are desired to be tested.
4. Exchange status: widen window or lower `--min-impact` only if hypothesis definition allows (document any change).
