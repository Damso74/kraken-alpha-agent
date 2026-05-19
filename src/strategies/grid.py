"""Fixed grid bot strategy — max 3 levels, 30% inventory cap, no martingale."""

from __future__ import annotations

from typing import Sequence

from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio

from .base import StrategySignal


class GridStrategy:
    name = "grid"
    grid_spacing_pct = 0.02
    max_levels = 3
    max_inventory_fraction = 0.30
    level_size_fraction = 0.10

    def __init__(self) -> None:
        self._anchor: float | None = None
        self._levels_filled = 0

    def warmup_bars(self) -> int:
        return 5

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        bar = candles[index]
        if self._anchor is None:
            self._anchor = bar.close

        pos = portfolio.position(symbol)
        prices = {symbol: bar.close}
        inv_frac = portfolio.position_fraction(symbol, prices)

        dip = (bar.close - self._anchor) / self._anchor if self._anchor else 0.0
        rise = -dip

        if (
            dip <= -self.grid_spacing_pct
            and self._levels_filled < self.max_levels
            and inv_frac < self.max_inventory_fraction
        ):
            self._levels_filled += 1
            self._anchor = bar.close
            return StrategySignal(
                "buy",
                self.level_size_fraction,
                f"grid buy level={self._levels_filled}",
            )

        if rise >= self.grid_spacing_pct and pos.quantity > 1e-12:
            self._levels_filled = max(0, self._levels_filled - 1)
            self._anchor = bar.close
            return StrategySignal("sell", min(1.0, self.level_size_fraction * 2), "grid take profit")

        return StrategySignal("hold", 0.0, "grid idle")
