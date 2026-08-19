"""SMA 20/50 trend-following bot strategy (paper MVP)."""

from __future__ import annotations

from collections.abc import Sequence

from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio

from .base import StrategySignal


def _sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / period


class TrendFollowingStrategy:
    name = "trend_following"
    fast_period = 20
    slow_period = 50
    max_position_fraction = 0.25

    def warmup_bars(self) -> int:
        return self.slow_period + 1

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        closes = [c.close for c in candles[: index + 1]]
        fast = _sma(closes, self.fast_period)
        slow = _sma(closes, self.slow_period)
        if fast is None or slow is None:
            return StrategySignal("hold", 0.0, "warming up")

        pos = portfolio.position(symbol)
        if fast > slow and pos.quantity <= 1e-12:
            return StrategySignal(
                "buy",
                self.max_position_fraction,
                f"sma{self.fast_period}>{self.slow_period}",
            )
        if fast < slow and pos.quantity > 1e-12:
            return StrategySignal("sell", 1.0, f"sma{self.fast_period}<{self.slow_period}")
        return StrategySignal("hold", 0.0, "no crossover")
