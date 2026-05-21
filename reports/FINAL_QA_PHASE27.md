# Final QA — Phase 27

## Collectors (27A)
- Basis collector: `src/data/collectors/binance_basis_public.py` ✅
- Basis readiness manifest: **True** (BTC/ETH 6603 rows)
- Tests: `tests/test_basis_overlay_phase27.py` ✅

## Overlay tournament (27B)
- Script: `scripts/run_basis_overlay_tournament_phase27.py` ✅
- Summary present: **True**
- validation_candidate: **0**

## OI depth (27C)
- Audit script: `scripts/audit_derivatives_depth_phase27.py` ✅
- OI label: **experimental** (6/6 entries)
- Report: `PHASE27_OI_DATA_DEPTH.md` ✅

## ETH 4h autopsy (27D)
- Script: `scripts/run_eth4h_overlay_autopsy_phase27.py` ✅
- useful_overlay: **2**, decorative: **1**, kill_overlay: **0**
- Tests: `tests/test_eth4h_overlay_autopsy_phase27.py` ✅

## pytest
- Full suite green (845+ tests)

## Sensitive files unchanged
- `execution.py`, `risk.py`, `futures_kraken_cli.py`, `web/`, `config.yaml` — **not modified**

## Micro-live
- **NO-GO** (`MICRO_LIVE_GO_NO_GO_PHASE27.md`)
