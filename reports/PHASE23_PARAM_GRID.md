# Phase 23 — Grille de paramètres (verrouillée avant runs)

**Date de verrouillage :** 2026-05-20  
**Politique :** aucun tuning post-hoc sur les résultats du factory.

## Périmètre

| Dimension | Valeurs |
|-----------|---------|
| Stratégies | `ema_crossover`, `donchian_breakout`, `atr_breakout`, `trend_following` |
| Timeframes | `1d`, `4h` uniquement (pas `1h`) |
| Actifs | `BTC`, `ETH`, `SOL` |
| Variantes | `baseline`, `slow`, `fast` |
| Overlays (Axe B) | `off`, `vol`, `panic`, `both` |

**Runs factory (complet) :** 4 × 3 × 3 × 2 × 4 = **288** backtests cache-only.

**Fenêtre d'évaluation factory :** par défaut `--max-bars 1000` (dernières barres) pour budget CPU honnête sur overlay régime O(n²) ; `--max-bars 0` = historique complet.

## Variantes (pré-déclarées)

Baselines = presets Phase 15/16 (`src/strategies/presets.py`).

| Stratégie | Paramètres scalés | Slow | Fast |
|-----------|-------------------|------|------|
| `ema_crossover` | `fast_period`, `slow_period` | ×1.20 | ×0.80 |
| `trend_following` | `fast_period`, `slow_period` | ×1.20 | ×0.80 |
| `donchian_breakout` | `channel_period` | ×1.15 | ×0.85 |
| `atr_breakout` | `atr_period`, `lookback` | ×1.20 | ×0.80 |

### Baselines numériques

| Stratégie | 1d | 4h |
|-----------|----|----|
| ema_crossover | fast=12, slow=26 | fast=18, slow=50 |
| trend_following | fast=20, slow=50 | fast=24, slow=72 |
| donchian_breakout | channel=20 | channel=24 |
| atr_breakout | atr=14, lookback=20 | atr=14, lookback=24 |

## Overlays (Axe B)

| Mode | Comportement |
|------|----------------|
| `off` | Stratégie nue |
| `vol` | `wrap_with_vol_targeting` (presets Phase 16) |
| `panic` | `RegimeOverlayStrategy` — panic/range → cash, high_vol → scale 0.25, trend_up → 1.0 |
| `both` | vol puis panic (ordre fixe) |

## Walk-forward (Axe D)

- Fees : **40 bps** + slippage **5 bps**
- Verdict autorisé : **`paper_candidate_walkforward` uniquement**
- Interdit en rapport Phase 23 : `paper_candidate` sans suffixe `_walkforward`
- Gates additionnels : drawdown full < B&H, trades totaux ≥ 8, turnover ≤ 25, pas de dominance mono-actif > 85 %

## Regime overlay benchmark (Axe D2)

- Actifs : BTC, ETH
- Timeframes : 1d, 4h
- Stratégies : ema_crossover, donchian_breakout, trend_following (variante `baseline`)
- Modes comparés : `standalone`, `regime_overlay`, `buy_and_hold`
