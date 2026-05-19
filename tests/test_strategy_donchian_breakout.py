from __future__ import annotations

from src.bot.portfolio import PaperPortfolio
from src.strategies.donchian_breakout import DonchianBreakoutStrategy
from tests.conftest_bot import synthetic_uptrend


def test_donchian_breakout_runs() -> None:
    candles = synthetic_uptrend(80)
    strat = DonchianBreakoutStrategy()
    portfolio = PaperPortfolio(cash_usd=1000.0)
    for i in range(strat.warmup_bars(), len(candles)):
        sig = strat.on_bar(i, candles, portfolio, "BTC")
        assert sig.action in ("buy", "sell", "hold")
