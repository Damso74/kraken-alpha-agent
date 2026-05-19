from __future__ import annotations

from src.strategies.volatility_targeting import scale_size_for_vol


def test_vol_scale_bounds() -> None:
    closes = [100.0] * 25
    scaled, factor = scale_size_for_vol(
        0.25,
        closes,
        vol_lookback=20,
        target_vol_daily=0.02,
        min_scale=0.25,
        max_scale=1.0,
    )
    assert 0.0 <= scaled <= 0.25
    assert 0.25 <= factor <= 1.0
