"""Donchian channel breakout strategy (long-only)."""

from __future__ import annotations

from typing import Sequence

from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio

from .base import StrategySignal


class DonchianBreakoutStrategy:
    name = "donchian_breakout"
    channel_period = 20
    max_position_fraction = 0.25

    def warmup_bars(self) -> int:
        return self.channel_period + 1

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        if index < self.channel_period:
            return StrategySignal("hold", 0.0, "warming up")

        prior = candles[index - self.channel_period : index]
        if len(prior) < self.channel_period:
            return StrategySignal("hold", 0.0, "warming up")

        upper = max(c.high for c in prior)
        lower = min(c.low for c in prior)
        close = candles[index].close
        pos = portfolio.position(symbol)

        if close > upper and pos.quantity <= 1e-12:
            return StrategySignal(
                "buy",
                self.max_position_fraction,
                f"close>{upper:.4f}",
            )
        if close < lower and pos.quantity > 1e-12:
            return StrategySignal("sell", 1.0, f"close<{lower:.4f}")
        return StrategySignal("hold", 0.0, "inside channel")
