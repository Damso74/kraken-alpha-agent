"""Tests for paper risk manager."""

from __future__ import annotations

from src.bot.orders import Order
from src.bot.risk_manager import RiskConfig, RiskManager


def test_deny_max_position_fraction() -> None:
    rm = RiskManager(RiskConfig(max_position_fraction=0.10))
    rm.on_bar(equity=1000.0, timestamp="2024-01-01")
    order = Order("BTC", "buy", 1.0, 200.0, 0, 1, "t")
    d = rm.validate_order(
        order,
        equity=1000.0,
        cash_usd=1000.0,
        position_fraction=0.0,
        exposure_fraction=0.0,
    )
    assert d.verdict == "deny"
    assert d.rule == "max_position_fraction"


def test_allow_small_order() -> None:
    rm = RiskManager()
    rm.on_bar(equity=1000.0, timestamp="2024-01-01")
    order = Order("BTC", "buy", 0.01, 100.0, 0, 1, "t")
    d = rm.validate_order(
        order,
        equity=1000.0,
        cash_usd=1000.0,
        position_fraction=0.0,
        exposure_fraction=0.0,
    )
    assert d.verdict == "allow"
