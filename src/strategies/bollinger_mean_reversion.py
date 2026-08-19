"""Bollinger band mean-reversion strategy (long-only)."""

from __future__ import annotations

from collections.abc import Sequence

from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio

from .base import StrategySignal


def _bollinger(
    closes: list[float], period: int, num_std: float
) -> tuple[float, float, float] | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    std = var**0.5
    upper = mean + num_std * std
    lower = mean - num_std * std
    return lower, mean, upper


class BollingerMeanReversionStrategy:
    name = "bollinger_mean_reversion"
    period = 20
    num_std = 2.0
    max_holding_bars = 7
    max_position_fraction = 0.25

    def warmup_bars(self) -> int:
        return self.period + 1

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        closes = [c.close for c in candles[: index + 1]]
        bands = _bollinger(closes, self.period, self.num_std)
        if bands is None:
            return StrategySignal("hold", 0.0, "warming up")
        lower, mid, upper = bands
        close = closes[-1]
        pos = portfolio.position(symbol)

        if pos.quantity > 1e-12 and pos.bars_held >= self.max_holding_bars:
            return StrategySignal("sell", 1.0, "max holding period")

        if close <= lower and pos.quantity <= 1e-12:
            return StrategySignal(
                "buy",
                self.max_position_fraction,
                f"close<={lower:.4f}",
            )
        if pos.quantity > 1e-12 and (close >= mid or close >= upper):
            return StrategySignal("sell", 1.0, f"close={close:.4f} reverted")
        return StrategySignal("hold", 0.0, f"bb mid={mid:.4f}")
