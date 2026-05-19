# Runtime smoke — event study scripts (Phase 3)

Generated: **2026-05-19** (Agent 6). Environment: Windows 11, PowerShell,
`.\.venv\Scripts\Activate.ps1`. No `config.yaml` or live profile changes.

## Summary

| Status | Scripts |
|--------|---------|
| **OK** | All 7 scripts: `--help` exits 0 |
| **cache-required** | `event_study_wikipedia`, `event_study_eth_gas`, `event_study_exchange_status`, `demo_event_study` (empty / incomplete cache → exit 2, clear stderr) |
| **blocked** (offline `--use-cache-only` incomplete) | `event_study_stablecoins` (supply cache can pass but **Kraken OHLC still live**), `event_study_calendar`, `event_study_deribit_expiry` (flag present, **no collector cache** — OHLC-only) |

Automated (no network): `tests/test_runtime_smoke_event_study.py`.

## Cache inventory at smoke time

| Path | Present | Notes |
|------|---------|-------|
| `data/collector_cache/defillama.json` | yes (~646 KiB) | Legitimate prior fetch; not fabricated for smoke |
| `data/collector_cache/wikimedia.json` | no | |
| `data/collector_cache/status_pages.json` | no | |
| `data/collector_cache/etherscan_gas_history.json` | no | |
| `data/external_cache/fear_greed.json` | yes (~8 KiB) | Does not cover arbitrary `--days` windows |
| `data/collector_cache/README.md` | yes | Schema / `--use-cache-only` contract |

Expected cache shapes (structure only): see
[`data/collector_cache/README.md`](../../data/collector_cache/README.md).

## Results table

| Script | `--help` | `--use-cache-only` | `--output-json` / `--json-out` | Status | Notes |
|--------|----------|-------------------|--------------------------------|--------|-------|
| `event_study_stablecoins.py` | OK (0) | **blocked** / partial | OK when run completes | **blocked** (full offline) | Empty cache → exit **2**, message cites DefiLlama path + README. With repo `defillama.json`, supply leg is cache-only but script still calls **Kraken public OHLC** (httpx). UTF-8 console recommended; `_console_text` replaces `→` for cp1252. |
| `event_study_wikipedia.py` | OK (0) | **cache-required** | Not written on failure | **cache-required** | Exit **2**: `use_cache_only: network fetch disabled` + path to `wikimedia.json`. |
| `event_study_eth_gas.py` | OK (0) | **cache-required** | Not written on failure | **cache-required** | Exit **2**: no `etherscan_gas_history.json` (needs ≥ `lookback+1` daily rows). |
| `event_study_exchange_status.py` | OK (0) | **cache-required** | Not written on failure | **cache-required** | Exit **2**: missing `status_pages.json`, Statuspage hint. |
| `event_study_calendar.py` | OK (0) | N/A (no collector feed) | Not tested (needs OHLC) | **blocked** | `--use-cache-only` in argparse but **ignored**; events from OHLC timestamps only. |
| `event_study_deribit_expiry.py` | OK (0) | N/A (no collector feed) | Not tested (needs OHLC) | **blocked** | Same as calendar; monthly expiry from OHLC only. |
| `demo_event_study.py` | OK (0) | **cache-required** | `--json-out` (not `--output-json`) | **cache-required** | Exit **2** for `--days 30` + `--use-cache-only`: F&G cache does not cover window. Still would call Kraken OHLC after F&G if cache matched. |

## Artifacts in this directory

| File | Description |
|------|-------------|
| `event_study_stablecoins_cache_only.json` | Produced with UTF-8 + existing `defillama.json` + live OHLC (research harness output; 0 events on 30d window). |
| `*_help.txt` / `*_cache_stderr.txt` | Captured stdout/stderr from manual smoke run. |
| `_empty_defillama.json` | Intentionally missing cache path for clean exit-2 probe. |

No JSON artifacts for scripts that failed before `write_json_report` / `--json-out`.

## Commands (reproduce)

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONIOENCODING = "utf-8"

# Help (all scripts)
python scripts/event_study_stablecoins.py --help

# Cache-only failure (no network on collector leg)
python scripts/event_study_wikipedia.py --use-cache-only `
  --cache-path reports/runtime_smoke/_empty_wikimedia.json `
  --output-json reports/runtime_smoke/event_study_wikipedia_cache_only.json `
  --days 30 --n-placebos 5

# Unit tests (hermetic)
pytest tests/test_runtime_smoke_event_study.py -q
```

## Exact status list

- **OK**: `--help` on all seven scripts.
- **cache-required**: `event_study_wikipedia`, `event_study_eth_gas`, `event_study_exchange_status`, `demo_event_study`.
- **blocked**: `event_study_calendar`, `event_study_deribit_expiry` (offline cache-only N/A); `event_study_stablecoins` for **strict** no-network runs when DefiLlama cache is populated (OHLC leg remains).
