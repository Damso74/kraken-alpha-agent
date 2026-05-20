"""Tests for kill switch (Phase 20)."""

from __future__ import annotations

from pathlib import Path

from src.bot.kill_switch import (
    GuardrailConfig,
    GuardrailState,
    emergency_stop_active,
    evaluate_guardrails,
)


def test_emergency_stop_file(tmp_path: Path) -> None:
    stop = tmp_path / "STOP_TRADING"
    assert not emergency_stop_active(stop)
    stop.write_text("stop", encoding="utf-8")
    assert emergency_stop_active(stop)


def test_guardrails_block_without_manual_approval() -> None:
    cfg = GuardrailConfig(dry_run_passed=True, manual_approval_required=True)
    state = GuardrailState(manual_approval_granted=False)
    d = evaluate_guardrails(
        config=cfg, state=state, symbol="BTC", notional_usd=5.0
    )
    assert not d.allowed
    assert d.reason == "manual_approval_required"


def test_guardrails_allow_when_ok() -> None:
    cfg = GuardrailConfig(dry_run_passed=True, manual_approval_required=False)
    state = GuardrailState(current_equity_usd=10.0, starting_capital_usd=10.0)
    d = evaluate_guardrails(
        config=cfg, state=state, symbol="BTC", notional_usd=5.0
    )
    assert d.allowed
