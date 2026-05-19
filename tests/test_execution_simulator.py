"""Tests for execution simulator slippage and fees."""

from __future__ import annotations

from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.orders import Order


def test_buy_slippage_and_fee() -> None:
    sim = ExecutionSimulator(ExecutionConfig(fee_bps=40, slippage_bps=10))
    order = Order("BTC", "buy", 1.0, 100.0, 0, 1, "s")
    result = sim.execute_market(order, cash_usd=10_000, position_qty=0.0)
    assert result.fill is not None
    assert result.fill.price == 100.0 * 1.001
    assert result.fill.fee_usd == result.fill.notional_usd * 0.004


def test_reject_insufficient_cash() -> None:
    sim = ExecutionSimulator()
    order = Order("BTC", "buy", 10.0, 100.0, 0, 1, "s")
    result = sim.execute_market(order, cash_usd=10.0, position_qty=0.0)
    assert result.rejected
    assert result.reject_reason == "insufficient_cash"
