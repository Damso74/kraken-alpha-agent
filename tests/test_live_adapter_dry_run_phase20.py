"""Tests for live adapter dry-run (Phase 20)."""

from __future__ import annotations

from src.bot.live_adapter_dry_run import (
    LiveOrderIntent,
    convert_paper_order_to_live_intent,
    dry_run_submit_order,
    estimate_fees,
    estimate_min_notional,
    validate_live_order_intent,
)
from src.bot.orders import Order


def test_dry_run_never_without_manual_approval() -> None:
    intent = LiveOrderIntent("BTC", "buy", 0.001, 10.0, 100_000.0, "test", "r")
    result = dry_run_submit_order(intent, manual_approval=False)
    assert result.status == "blocked"
    assert "manual_approval" in result.message


def test_dry_run_with_approval() -> None:
    intent = LiveOrderIntent("BTC", "buy", 0.001, 10.0, 100_000.0, "test", "r")
    result = dry_run_submit_order(intent, manual_approval=True)
    assert result.status == "dry_run"
    assert "no_venue" in result.message


def test_validate_blocks_oversized_notional() -> None:
    intent = LiveOrderIntent("BTC", "buy", 1.0, 100.0, 100.0, "t", "r")
    ok, reason = validate_live_order_intent(intent, max_notional_usd=20.0)
    assert not ok
    assert "notional" in reason


def test_convert_paper_order() -> None:
    order = Order("BTC", "buy", 0.01, 100.0, 0, 0, "s", "r")
    intent = convert_paper_order_to_live_intent(order, price=100.0)
    assert intent.notional_usd == 1.0


def test_estimate_fees_and_min_notional() -> None:
    assert estimate_fees(100.0) > 0
    assert estimate_min_notional(asset="BTC") >= 5.0
