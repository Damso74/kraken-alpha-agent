"""Phase 15 preset tests — locked parameters."""

from __future__ import annotations

import pytest

from src.strategies.presets import (
    PHASE15_PRESETS,
    build_strategy,
    get_strategy_preset,
    list_presets,
    validate_preset,
)


def test_list_presets() -> None:
    keys = list_presets()
    assert keys == ["phase15_1d", "phase15_1h", "phase15_4h"]


def test_validate_preset() -> None:
    assert validate_preset("phase15_1d")
    assert validate_preset("phase15_4h", "trend_following")
    assert not validate_preset("phase15_9d")


@pytest.mark.parametrize("timeframe", ["1d", "4h", "1h"])
def test_all_strategies_have_presets(timeframe: str) -> None:
    for name in ("trend_following", "breakout", "mean_reversion", "grid"):
        params = get_strategy_preset(name, timeframe)
        assert isinstance(params, dict)
        assert params


def test_phase15_1d_trend_exact() -> None:
    p = PHASE15_PRESETS["phase15_1d"]["trend_following"]
    assert p["fast_period"] == 20
    assert p["slow_period"] == 50
    assert p["max_position_fraction"] == 0.25


def test_build_strategy_applies_params() -> None:
    s = build_strategy("trend_following", "4h")
    assert s.fast_period == 24
    assert s.slow_period == 72
