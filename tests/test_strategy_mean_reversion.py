from __future__ import annotations

from src.bot.portfolio import PaperPortfolio
from src.strategies.mean_reversion import MeanReversionStrategy
from tests.conftest_bot import synthetic_range


def test_mean_reversion_strategy_runs() -> None:
    candles = synthetic_range(60)
    strat = MeanReversionStrategy()
    portfolio = PaperPortfolio(cash_usd=1000.0)
    for i in range(strat.warmup_bars(), len(candles)):
        sig = strat.on_bar(i, candles, portfolio, "ETH")
        assert sig.action in ("buy", "sell", "hold")
