"""Tests for paper backtest engine."""

from __future__ import annotations

from collections.abc import Sequence

from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.paper_engine import BotCandle, run_paper_backtest
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_manager import RiskManager
from src.strategies.base import StrategySignal
from src.strategies.trend_following import TrendFollowingStrategy
from tests.conftest_bot import synthetic_uptrend


class _ScriptedStrategy:
    """Achete a une barre donnee, revend a une autre — aller-retour deterministe."""

    name = "scripted"

    def __init__(self, buy_at: int, sell_at: int) -> None:
        self.buy_at = buy_at
        self.sell_at = sell_at

    def warmup_bars(self) -> int:
        return 0

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        if index == self.buy_at:
            return StrategySignal("buy", 0.2, "scripted entry")
        if index == self.sell_at:
            return StrategySignal("sell", 1.0, "scripted exit")
        return StrategySignal("hold", 0.0, "")


def _run_scripted(strategy: _ScriptedStrategy, candles: list[BotCandle]):
    return run_paper_backtest(
        candles,
        strategy,
        PaperPortfolio(cash_usd=1000.0),
        RiskManager(),
        ExecutionSimulator(ExecutionConfig(fee_bps=10.0, slippage_bps=1.0)),
        BotJournal(),
        {"starting_equity": 1000.0, "use_classify_verdict": False},
        symbol="BTC",
    )


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


def test_winning_round_trip_is_counted_as_a_win() -> None:
    """Defaut #8 : le PnL par trade etait perdu, win_rate restait a 0."""
    candles = synthetic_uptrend(40)
    result = _run_scripted(_ScriptedStrategy(buy_at=2, sell_at=30), candles)

    assert result.metrics.total_return_pct > 0.0
    assert result.metrics.win_rate_pct == 100.0
    assert result.metrics.round_trip_count == 1


def test_losing_round_trip_is_counted_as_a_loss() -> None:
    """Symetrique du precedent : une sortie perdante ne doit pas compter gagnante."""
    candles = synthetic_uptrend(40)
    downtrend = [
        BotCandle(
            timestamp=c.timestamp,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        for c in reversed(candles)
    ]
    result = _run_scripted(_ScriptedStrategy(buy_at=2, sell_at=30), downtrend)

    assert result.metrics.win_rate_pct == 0.0
    assert result.metrics.round_trip_count == 1


def test_open_position_leaves_win_rate_unevaluable() -> None:
    """Sans sortie, win_rate n'est pas 0 % : il est non evaluable."""
    candles = synthetic_uptrend(40)
    result = _run_scripted(_ScriptedStrategy(buy_at=2, sell_at=-1), candles)

    assert result.metrics.trade_count == 1
    assert result.metrics.win_rate_pct is None
    assert result.metrics.cost_drag_undefined is True
    assert result.metrics.round_trip_count == 0
