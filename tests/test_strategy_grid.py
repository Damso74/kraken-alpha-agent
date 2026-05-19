from __future__ import annotations

from src.bot.portfolio import PaperPortfolio
from src.strategies.grid import GridStrategy
from tests.conftest_bot import synthetic_range


def test_grid_strategy_respects_max_levels() -> None:
    candles = synthetic_range(80)
    strat = GridStrategy()
    portfolio = PaperPortfolio(cash_usd=1000.0)
    buys = 0
    for i in range(strat.warmup_bars(), len(candles)):
        sig = strat.on_bar(i, candles, portfolio, "BTC")
        if sig.action == "buy":
            buys += 1
    assert buys <= strat.max_levels + 2
