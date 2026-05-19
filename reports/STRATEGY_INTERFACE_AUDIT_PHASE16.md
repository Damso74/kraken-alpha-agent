# Phase 16 — Strategy interface audit (Agent 75)

**Date :** 2026-05-19

## Contrat existant (`src/strategies/base.py`)

```python
class BaseStrategy(Protocol):
    name: str
    def warmup_bars(self) -> int: ...
    def on_bar(index, candles, portfolio, symbol) -> StrategySignal | None: ...
```

`StrategySignal` : `action` ∈ {buy, sell, hold}, `size_fraction`, `reason`.

## Stratégies Phase 14/15 (inchangées)

| Fichier | Classe | Warmup | Long-only |
|---------|--------|--------|-----------|
| `trend_following.py` | `TrendFollowingStrategy` | slow_period+1 | ✅ |
| `breakout.py` | `BreakoutStrategy` | lookback+1 | ✅ |
| `mean_reversion.py` | `MeanReversionStrategy` | lookback+1 | ✅ |
| `grid.py` | `GridStrategy` | 5 | ✅ |

## Nouvelles stratégies Phase 16

| Fichier | Classe | Warmup | Anti-leakage |
|---------|--------|--------|--------------|
| `ema_crossover.py` | `EmaCrossoverStrategy` | slow+1 | closes[:index+1] |
| `donchian_breakout.py` | `DonchianBreakoutStrategy` | channel+1 | canal sur barres **prior** à index |
| `rsi_mean_reversion.py` | `RsiMeanReversionStrategy` | rsi_period+2 | RSI sur historique courant |
| `bollinger_mean_reversion.py` | `BollingerMeanReversionStrategy` | period+1 | bandes sur closes passées |
| `atr_breakout.py` | `AtrBreakoutStrategy` | max(atr,lookback)+2 | ATR/ref sur `prior = history[:-1]` |
| `volatility_targeting.py` | `VolatilityTargetingOverlay` | max(inner, vol_lookback+2) | overlay post-signal, scale buy only |

## Presets

- Phase 15 : `PHASE15_PRESETS` (4 stratégies × 3 TF).
- Phase 16 : `PHASE16_ZOO_PRESETS` (5 stratégies × 3 TF) + `PHASE16_VOL_TARGET_PRESETS`.
- Factory : `build_strategy(name, timeframe)` dans `presets.py`.

## Verdict audit

**Compatible** — aucun refactor global requis ; overlay vol composable via wrapper sans modifier `paper_engine.py`.
