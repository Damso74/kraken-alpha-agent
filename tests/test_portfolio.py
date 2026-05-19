"""Tests for paper portfolio."""

from __future__ import annotations

import pytest

from src.bot.orders import Fill
from src.bot.portfolio import PaperPortfolio


def test_apply_fill_buy_sell_roundtrip() -> None:
    p = PaperPortfolio(cash_usd=1000.0)
    buy = Fill("BTC", "buy", 0.1, 100.0, 4.0, 10.0, 0, 1, "t")
    p.apply_fill(buy)
    assert p.position("BTC").quantity == 0.1
    sell = Fill("BTC", "sell", 0.1, 110.0, 4.4, 11.0, 1, 2, "t")
    p.apply_fill(sell)
    assert p.position("BTC").quantity == 0.0
    assert p.fees_paid_usd == pytest.approx(8.4)
    assert p.cash_usd == pytest.approx(992.6)


def test_equity_mark_to_market() -> None:
    p = PaperPortfolio(cash_usd=500.0)
    p.apply_fill(Fill("ETH", "buy", 1.0, 50.0, 2.0, 50.0, 0, 1, "t"))
    eq = p.equity({"ETH": 60.0})
    assert eq == 500.0 - 52.0 + 60.0
