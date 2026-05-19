"""Tests for paper backtest engine."""

from __future__ import annotations

from src.bot.execution_simulator import ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.paper_engine import run_paper_backtest
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_manager import RiskManager
from src.strategies.trend_following import TrendFollowingStrategy
from tests.conftest_bot import synthetic_uptrend


def test_run_paper_backtest_produces_equity_curve() -> None:
    candles = synthetic_uptrend(100)
    portfolio = PaperPortfolio(cash_usd=1000.0)
    result = run_paper_backtest(
        candles,
        TrendFollowingStrategy(),
        portfolio,
        RiskManager(),
        ExecutionSimulator(),
        BotJournal(),
        {"starting_equity": 1000.0},
        symbol="BTC",
    )
    assert len(result.equity_curve) == len(candles)
    assert result.metrics.starting_equity == 1000.0
