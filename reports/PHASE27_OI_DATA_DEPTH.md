# Phase 27 — OI data depth audit

## Verdict

- OI series labeled **experimental** when row_count < 500 or span < 180 days.
- Experimental OI entries: **6**
- Coinglass / paid aggregators: **not integrated** (API key required).
- Binance `openInterestHist` API max lookback: **~30 days** (documented).

## OI entries

| asset | period | rows | span_days | label | validation_candidate |
|-------|--------|------|-----------|-------|----------------------|
| BTC | 4h | 180 | 29.8 | experimental | False |
| BTC | 1d | 30 | 29.0 | experimental | False |
| ETH | 4h | 180 | 29.8 | experimental | False |
| ETH | 1d | 30 | 29.0 | experimental | False |
| SOL | 4h | 0 | 0.0 | experimental | False |
| SOL | 1d | 0 | 0.0 | experimental | False |

## Funding readiness (Phase 26 cache)

- available_count: **6**

## Basis readiness (Phase 27 cache)

- available_count: **2**

## Recommendation

Keep OI experimental; exclude from validation_candidate gates until a documented long-history source is wired.
