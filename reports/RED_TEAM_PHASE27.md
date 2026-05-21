# Red team — Phase 27

1. **Basis lookahead?** Alignment uses last basis row at or before candle open — no future mark price.
2. **Spot/perp venue mismatch?** Both Binance USDT-M; not Kraken xStocks — research proxy only.
3. **Basis z warmup?** First ~30 bars have null z-score → defaults to allow (conservative).
4. **OI still experimental?** Yes — 30d window; OI excluded from validation_candidate gates.
5. **Overlay = risk only?** Tournament shows 4 overlay_only (DD reduction) vs 1 kill; no improved alpha gate passed.
6. **ETH concentration?** 3/4 funding_basis_best cells are ETH — monitor asset concentration.
7. **Dangerous for micro-live?** Yes — derivatives overlay is research; PEDSL-CY xStocks blocked.

## Verdict

Phase 27 confirms basis adds marginal signal over funding-only on ETH 4h, but remains a **risk overlay**, not a live trading unlock. **NO-GO micro-live.**
