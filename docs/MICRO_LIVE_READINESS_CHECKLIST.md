# Micro-live readiness checklist (Phase 20)

**Default verdict: NO-GO** until human approval and paper observation evidence exist.

## Pre-conditions

- [ ] Paper daemon observed ≥ 2–4 weeks (`reports/paper_live/`)
- [ ] Strategy passed walk-forward / regime router QA (Phase 17–18)
- [ ] Red team pass on all bot phases
- [ ] No `fix_required` on latest phase

## Capital & risk (budget 5–20 €)

- [ ] Max capital cap configured (≤ 20 € / ~20 USD)
- [ ] Max daily loss defined (e.g. 5 €)
- [ ] Max total loss defined (e.g. 10 €)
- [ ] Max position size ≤ 10 €
- [ ] Kill switch file tested (`reports/paper_daemon_state/STOP_TRADING`)

## Execution

- [ ] Dry-run adapter pass (`scripts/run_micro_live_simulation.py`)
- [ ] Manual approval required before any live intent
- [ ] Min order size / notional validated
- [ ] Fees + slippage estimates documented
- [ ] No automatic live loop

## API & secrets

- [ ] API keys **outside repo** (never commit `.env`)
- [ ] Trade-only key, no withdrawal permission
- [ ] IP allowlist if supported
- [ ] Key rotation plan documented

## Operational

- [ ] Logging + audit trail (`decisions.jsonl`, `trades.csv`)
- [ ] Rollback plan (flatten + revoke keys)
- [ ] Triple opt-in unchanged (`TRADING_MODE`, `LIVE_TRADING`, `ALLOW_LIVE_ORDERS`)
- [ ] Human operator confirms session

## Explicit non-goals

- No live order from Phase 20 code paths
- No Kraken CLI call from dry-run modules
- No merge to master without jury/hackathon decision
- Goal: test execution later — **not** profit chasing
