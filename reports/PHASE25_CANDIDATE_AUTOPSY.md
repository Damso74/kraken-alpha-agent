# Phase 25 — Candidate autopsy

**Cible :** `ETH_4h_trend_following_slow_off_h40_rolling`

## Verdict final : **kill**

- `paper_observation_candidate_count` : **0** (attendu 0 sauf passage intégral)
- Micro-live : **NO-GO**

## Baseline (re-run Phase 24 config)

- Excess vs B&H : **0.1388%**
- Max DD strat / B&H : **26.66325718745734%** / **29.217413920343134%**
- Trades : **55**
- Holdouts > B&H : **11** / **15**

## Tests

| Test | Verdict | Résumé |
|------|---------|--------|
| reproducibility | **pass** | Phase 24 metrics reproduced |
| param_sensitivity | **fail** | edge fragile to params |
| fee_sensitivity | **pass** | survives default 40bps/5bps slippage (marginal at high fees) |
| period_splits | **fail** | 1 periods beat B&H (need 2) |
| asset_placebo | **pass** | 1 placebo cell(s) also beat B&H |
| trade_concentration | **pass** | top3 share 34.4% OK |
| drawdown_acceptability | **fail** | DD benefit insufficient |

## Critères passage (paper observation)

Tous requis : reproductibilité, fees 40 bps, ±10% params, multi-période, pas de concentration trades, DD significativement < B&H, Calmar > B&H, red team OK.

## Conclusion

Le candidat ne survit pas l'autopsie ultra-stricte. **Kill** — ne pas activer paper observation ni live.

