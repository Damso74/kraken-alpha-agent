"""ATR-filtered breakout strategy (long-only)."""

from __future__ import annotations

from collections.abc import Sequence

from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio

from .base import StrategySignal


def _atr(candles: Sequence[BotCandle], period: int) -> float | None:
    if len(candles) < period + 1:
        return None
    window = candles[-(period + 1) :]
    trs: list[float] = []
    for i in range(1, len(window)):
        hi = window[i].high
        lo = window[i].low
        prev_close = window[i - 1].close
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


class AtrBreakoutStrategy:
    name = "atr_breakout"
    atr_period = 14
    lookback = 20
    atr_multiplier = 1.5
    max_position_fraction = 0.25

    def warmup_bars(self) -> int:
        return max(self.atr_period, self.lookback) + 2

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        if index < self.warmup_bars() - 1:
            return StrategySignal("hold", 0.0, "warming up")

        history = candles[: index + 1]
        prior = history[:-1]
        if len(prior) < self.lookback:
            return StrategySignal("hold", 0.0, "warming up")

        atr_val = _atr(prior, self.atr_period)
        if atr_val is None:
            return StrategySignal("hold", 0.0, "warming up")

        ref_window = prior[-self.lookback :]
        ref_high = max(c.high for c in ref_window)
        threshold = ref_high + self.atr_multiplier * atr_val
        close = history[-1].close
        pos = portfolio.position(symbol)

        if close > threshold and pos.quantity <= 1e-12:
            return StrategySignal(
                "buy",
                self.max_position_fraction,
                f"close>{threshold:.4f}",
            )
        if pos.quantity > 1e-12 and close < ref_high:
            return StrategySignal("sell", 1.0, f"close<{ref_high:.4f} exit")
        return StrategySignal("hold", 0.0, "no atr breakout")
