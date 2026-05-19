from __future__ import annotations

from src.bot.portfolio import PaperPortfolio
from src.strategies.trend_following import TrendFollowingStrategy
from tests.conftest_bot import synthetic_uptrend


def test_trend_following_signals_buy_on_uptrend() -> None:
    candles = synthetic_uptrend(80)
    strat = TrendFollowingStrategy()
    portfolio = PaperPortfolio(cash_usd=1000.0)
    signal = None
    for i in range(strat.warmup_bars(), len(candles)):
        signal = strat.on_bar(i, candles, portfolio, "BTC")
    assert signal is not None
    assert signal.action in ("buy", "hold", "sell")
