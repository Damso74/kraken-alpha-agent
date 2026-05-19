"""EMA crossover trend strategy (long-only, paper bot)."""

from __future__ import annotations

from typing import Sequence

from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio

from .base import StrategySignal


def _ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1.0 - k)
    return ema


class EmaCrossoverStrategy:
    name = "ema_crossover"
    fast_period = 12
    slow_period = 26
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
        fast = _ema(closes, self.fast_period)
        slow = _ema(closes, self.slow_period)
        if fast is None or slow is None:
            return StrategySignal("hold", 0.0, "warming up")

        pos = portfolio.position(symbol)
        if fast > slow and pos.quantity <= 1e-12:
            return StrategySignal(
                "buy",
                self.max_position_fraction,
                f"ema{self.fast_period}>{self.slow_period}",
            )
        if fast < slow and pos.quantity > 1e-12:
            return StrategySignal(
                "sell",
                1.0,
                f"ema{self.fast_period}<{self.slow_period}",
            )
        return StrategySignal("hold", 0.0, "no crossover")
