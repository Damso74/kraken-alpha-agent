"""Phase 28 — overlay shadow comparison unit tests."""

from __future__ import annotations

from src.bot.basis_crowding_overlay import BasisCrowdingState
from src.bot.overlay_shadow_compare import (
    ShadowComparisonRecord,
    append_shadow_comparison,
    build_shadow_record,
    load_shadow_comparisons,
    overlay_blocks_trade,
    summarize_shadow,
)
from src.strategies.base import StrategySignal


def test_build_shadow_record_allow() -> None:
    standalone = StrategySignal("buy", 0.25, "trend_up")
    overlay = StrategySignal("buy", 0.25, "ok")
    state = BasisCrowdingState("allow", 0.2, 0.1, False, False, "neutral")
    rec = build_shadow_record(
        timestamp=1_700_000_000,
        price=2000.0,
        standalone_sig=standalone,
        overlay_sig=overlay,
        overlay_state=state,
        bar_index=80,
        warmup=65,
        buy_hold_in_market=False,
    )
    assert rec.raw_signal == "buy"
    assert rec.overlay_decision == "allow"
    assert rec.standalone_would_trade is True
    assert rec.overlay_blocks is False
    assert rec.effective_action == "buy"


def test_overlay_blocks_on_block_filter() -> None:
    standalone = StrategySignal("buy", 0.25, "trend_up")
    overlay = StrategySignal("hold", 0.0, "basis_crowding_block")
    state = BasisCrowdingState("block", 2.5, 2.5, False, False, "elevated")
    assert overlay_blocks_trade(standalone, state, overlay) is True


def test_append_and_summarize(tmp_path) -> None:
    rec = ShadowComparisonRecord(
        timestamp=1,
        price=100.0,
        raw_signal="buy",
        standalone_action="buy",
        overlay_decision="block",
        overlay_reason="test",
        funding_z=2.5,
        basis_z=2.0,
        standalone_would_trade=True,
        overlay_blocks=True,
        effective_action="hold",
        buy_and_hold_action="buy",
        cash_action="hold",
    )
    append_shadow_comparison(tmp_path, rec)
    rows = load_shadow_comparisons(tmp_path)
    assert len(rows) == 1
    summary = summarize_shadow(rows)
    assert summary["blocks"] == 1
    assert summary["standalone_trades"] == 1
    assert summary["block_rate_on_signals"] == 1.0
