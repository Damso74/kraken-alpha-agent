"""Volatility-targeting overlay — scales buy size_fraction by realized vol."""

from __future__ import annotations

import math
from collections.abc import Sequence

from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio

from .base import StrategySignal


def _realized_vol_daily(closes: list[float], lookback: int) -> float | None:
    if len(closes) < lookback + 1:
        return None
    window = closes[-(lookback + 1) :]
    rets: list[float] = []
    for i in range(1, len(window)):
        prev = window[i - 1]
        if prev <= 1e-18:
            continue
        rets.append((window[i] - prev) / prev)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(max(var, 0.0))


def scale_size_for_vol(
    size_fraction: float,
    closes: list[float],
    *,
    vol_lookback: int,
    target_vol_daily: float,
    min_scale: float,
    max_scale: float,
) -> tuple[float, float]:
    """Return (scaled_size, scale_factor)."""
    realized = _realized_vol_daily(closes, vol_lookback)
    if realized is None or realized <= 1e-12:
        return size_fraction, 1.0
    scale = target_vol_daily / realized
    scale = max(min_scale, min(max_scale, scale))
    return size_fraction * scale, scale


class VolatilityTargetingOverlay:
    """Wraps a base strategy and scales buy signals by inverse realized vol."""

    name = "volatility_targeting"

    def __init__(
        self,
        inner: object,
        *,
        vol_lookback: int = 20,
        target_vol_daily: float = 0.02,
        min_scale: float = 0.25,
        max_scale: float = 1.0,
    ) -> None:
        self._inner = inner
        self.vol_lookback = vol_lookback
        self.target_vol_daily = target_vol_daily
        self.min_scale = min_scale
        self.max_scale = max_scale
        inner_name = getattr(inner, "name", "strategy")
        self.name = f"{inner_name}+vol_target"

    def warmup_bars(self) -> int:
        inner_warmup = int(self._inner.warmup_bars())
        return max(inner_warmup, self.vol_lookback + 2)

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        signal = self._inner.on_bar(index, candles, portfolio, symbol)
        if signal is None or signal.action != "buy":
            return signal
        closes = [c.close for c in candles[: index + 1]]
        scaled, scale = scale_size_for_vol(
            signal.size_fraction,
            closes,
            vol_lookback=self.vol_lookback,
            target_vol_daily=self.target_vol_daily,
            min_scale=self.min_scale,
            max_scale=self.max_scale,
        )
        return StrategySignal(
            signal.action,
            scaled,
            f"{signal.reason} vol_scale={scale:.2f}",
        )


def wrap_with_vol_targeting(strategy: object, timeframe: str) -> VolatilityTargetingOverlay:
    """Apply Phase 16 vol-target preset for timeframe."""
    from src.strategies.presets import get_vol_targeting_preset

    params = get_vol_targeting_preset(timeframe)
    return VolatilityTargetingOverlay(strategy, **params)
