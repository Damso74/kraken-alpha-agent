"""RSI mean-reversion strategy (long-only)."""

from __future__ import annotations

from collections.abc import Sequence

from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio

from .base import StrategySignal


def _rsi(closes: list[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    window = closes[-(period + 1) :]
    gains = 0.0
    losses = 0.0
    for i in range(1, len(window)):
        delta = window[i] - window[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if gains + losses <= 1e-18:
        return 50.0
    rs = gains / max(losses, 1e-18)
    return 100.0 - (100.0 / (1.0 + rs))


class RsiMeanReversionStrategy:
    name = "rsi_mean_reversion"
    rsi_period = 14
    oversold = 30.0
    exit_rsi = 55.0
    max_holding_bars = 7
    max_position_fraction = 0.25

    def warmup_bars(self) -> int:
        return self.rsi_period + 2

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        closes = [c.close for c in candles[: index + 1]]
        rsi_val = _rsi(closes, self.rsi_period)
        if rsi_val is None:
            return StrategySignal("hold", 0.0, "warming up")

        pos = portfolio.position(symbol)
        if pos.quantity > 1e-12 and pos.bars_held >= self.max_holding_bars:
            return StrategySignal("sell", 1.0, "max holding period")

        if rsi_val <= self.oversold and pos.quantity <= 1e-12:
            return StrategySignal(
                "buy",
                self.max_position_fraction,
                f"rsi={rsi_val:.1f} oversold",
            )
        if pos.quantity > 1e-12 and rsi_val >= self.exit_rsi:
            return StrategySignal("sell", 1.0, f"rsi={rsi_val:.1f} exit")
        return StrategySignal("hold", 0.0, f"rsi={rsi_val:.1f}")
