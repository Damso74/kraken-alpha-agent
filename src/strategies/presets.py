"""Phase 15 pre-declared strategy presets per timeframe (no post-hoc tuning)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.strategies.breakout import BreakoutStrategy
from src.strategies.grid import GridStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.trend_following import TrendFollowingStrategy

# Locked before tournament — do not change after seeing results.
PHASE15_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "phase15_1d": {
        "trend_following": {
            "fast_period": 20,
            "slow_period": 50,
            "max_position_fraction": 0.25,
        },
        "breakout": {
            "lookback": 20,
            "max_position_fraction": 0.25,
        },
        "mean_reversion": {
            "lookback": 20,
            "entry_z": 1.5,
            "exit_z": 0.25,
            "max_holding_bars": 7,
            "max_position_fraction": 0.25,
        },
        "grid": {
            "grid_spacing_pct": 0.02,
            "max_levels": 3,
            "max_inventory_fraction": 0.30,
            "level_size_fraction": 0.10,
        },
    },
    "phase15_4h": {
        "trend_following": {
            "fast_period": 24,
            "slow_period": 72,
            "max_position_fraction": 0.20,
        },
        "breakout": {
            "lookback": 24,
            "max_position_fraction": 0.20,
        },
        "mean_reversion": {
            "lookback": 28,
            "entry_z": 1.6,
            "exit_z": 0.30,
            "max_holding_bars": 42,
            "max_position_fraction": 0.20,
        },
        "grid": {
            "grid_spacing_pct": 0.015,
            "max_levels": 3,
            "max_inventory_fraction": 0.25,
            "level_size_fraction": 0.08,
        },
    },
    "phase15_1h": {
        "trend_following": {
            "fast_period": 48,
            "slow_period": 120,
            "max_position_fraction": 0.15,
        },
        "breakout": {
            "lookback": 48,
            "max_position_fraction": 0.15,
        },
        "mean_reversion": {
            "lookback": 56,
            "entry_z": 1.8,
            "exit_z": 0.35,
            "max_holding_bars": 168,
            "max_position_fraction": 0.15,
        },
        "grid": {
            "grid_spacing_pct": 0.010,
            "max_levels": 3,
            "max_inventory_fraction": 0.20,
            "level_size_fraction": 0.06,
        },
    },
}

TIMEFRAME_TO_PRESET_KEY: dict[str, str] = {
    "1d": "phase15_1d",
    "4h": "phase15_4h",
    "1h": "phase15_1h",
}

STRATEGY_CLASSES = {
    "trend_following": TrendFollowingStrategy,
    "breakout": BreakoutStrategy,
    "mean_reversion": MeanReversionStrategy,
    "grid": GridStrategy,
}


def list_presets() -> list[str]:
    return sorted(PHASE15_PRESETS.keys())


def validate_preset(preset_key: str, strategy_name: str | None = None) -> bool:
    if preset_key not in PHASE15_PRESETS:
        return False
    if strategy_name is None:
        return True
    return strategy_name in PHASE15_PRESETS[preset_key]


def get_strategy_preset(strategy_name: str, timeframe: str) -> dict[str, Any]:
    """Return a deep copy of preset params for strategy/timeframe."""
    tf = timeframe.strip().lower()
    preset_key = TIMEFRAME_TO_PRESET_KEY.get(tf)
    if preset_key is None:
        raise KeyError(f"unsupported timeframe: {timeframe}")
    bucket = PHASE15_PRESETS[preset_key]
    if strategy_name not in bucket:
        raise KeyError(f"unknown strategy {strategy_name!r} for {preset_key}")
    return deepcopy(bucket[strategy_name])


def build_strategy(strategy_name: str, timeframe: str):
    """Instantiate a strategy with Phase 15 preset parameters applied."""
    params = get_strategy_preset(strategy_name, timeframe)
    cls = STRATEGY_CLASSES[strategy_name]
    inst = cls()
    for key, value in params.items():
        setattr(inst, key, value)
    return inst
