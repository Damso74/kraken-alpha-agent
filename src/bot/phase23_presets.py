"""Phase 23 low-frequency presets — locked before factory runs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.strategies.presets import STRATEGY_CLASSES, get_strategy_preset

PHASE23_LOWFREQ_STRATEGIES = (
    "ema_crossover",
    "donchian_breakout",
    "atr_breakout",
    "trend_following",
)

PHASE23_TIMEFRAMES = ("1d", "4h")
PHASE23_ASSETS = ("BTC", "ETH", "SOL")
PHASE23_VARIANTS = ("baseline", "slow", "fast")

# Period keys scaled ±20% (slow +20%, fast −20%); Donchian/ATR lookback ±15%.
_SLOW_SCALE = 1.20
_FAST_SCALE = 0.80
_DONCHIAN_SLOW = 1.15
_DONCHIAN_FAST = 0.85

_PERIOD_KEYS: dict[str, tuple[str, ...]] = {
    "ema_crossover": ("fast_period", "slow_period"),
    "trend_following": ("fast_period", "slow_period"),
    "donchian_breakout": ("channel_period",),
    "atr_breakout": ("atr_period", "lookback"),
}


def _scale_params(
    base: dict[str, Any],
    strategy: str,
    variant: str,
) -> dict[str, Any]:
    if variant == "baseline":
        return deepcopy(base)
    out = deepcopy(base)
    keys = _PERIOD_KEYS.get(strategy, ())
    if strategy == "donchian_breakout":
        scale = _DONCHIAN_SLOW if variant == "slow" else _DONCHIAN_FAST
    else:
        scale = _SLOW_SCALE if variant == "slow" else _FAST_SCALE
    for key in keys:
        if key in out and isinstance(out[key], (int, float)):
            out[key] = max(2, int(round(float(out[key]) * scale)))
    return out


def list_phase23_combos() -> list[tuple[str, str, str, str]]:
    """(strategy, variant, asset, timeframe) — overlay applied at run time."""
    return [
        (s, v, a, tf)
        for s in PHASE23_LOWFREQ_STRATEGIES
        for v in PHASE23_VARIANTS
        for a in PHASE23_ASSETS
        for tf in PHASE23_TIMEFRAMES
    ]


def phase23_run_id(
    asset: str,
    timeframe: str,
    strategy: str,
    variant: str,
    overlay: str,
) -> str:
    return f"{asset.upper()}_{timeframe}_{strategy}_{variant}_{overlay}"


def get_phase23_params(strategy: str, timeframe: str, variant: str) -> dict[str, Any]:
    if strategy not in PHASE23_LOWFREQ_STRATEGIES:
        raise KeyError(f"unsupported phase23 strategy: {strategy}")
    if variant not in PHASE23_VARIANTS:
        raise KeyError(f"unsupported variant: {variant}")
    base = get_strategy_preset(strategy, timeframe)
    return _scale_params(base, strategy, variant)


def build_phase23_strategy(strategy: str, timeframe: str, variant: str):
    params = get_phase23_params(strategy, timeframe, variant)
    cls = STRATEGY_CLASSES[strategy]
    inst = cls()
    for key, value in params.items():
        setattr(inst, key, value)
    return inst
