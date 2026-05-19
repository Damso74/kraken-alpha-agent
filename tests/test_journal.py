"""Tests for bot journal."""

from __future__ import annotations

from src.bot.journal import BotJournal
from src.bot.orders import Fill
from src.bot.risk_manager import RiskDecision


def test_journal_records_fill_and_decisions() -> None:
    j = BotJournal()
    j.log_signal(bar_index=1, timestamp=1, symbol="BTC", strategy="t", action="buy", reason="x", size_fraction=0.1)
    j.log_risk(bar_index=1, timestamp=1, symbol="BTC", decision=RiskDecision("allow"))
    j.log_fill(Fill("BTC", "buy", 0.1, 100.0, 1.0, 10.0, 1, 1, "t"))
    assert len(j.trades) == 1
    assert len(j.decisions_as_dicts()) == 3
