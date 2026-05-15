"""Exit-rules engine regression tests.

Covers the priorities defined in the user brief: stop-loss → take-profit
→ momentum → time → flatten-before-close. No test in this file places a
real order; the engine is pure and we feed it synthetic ``Position`` /
config dicts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.exit_rules import (
    ExitDecision,
    evaluate_exit_rules,
    flatten_before_close_exit,
    momentum_exit,
    stop_loss_exit,
    take_profit_exit,
    time_exit,
)
from src.schemas import Position


def _make_position(
    *,
    quantity: float = 1.0,
    avg: float = 100.0,
    market: float = 100.0,
    opened_at: str | None = None,
) -> Position:
    return Position(
        symbol="AAPLx",
        quantity=quantity,
        avg_entry_price=avg,
        market_price=market,
        notional_usd=quantity * market,
        opened_at=opened_at,
    )


class _ExitCfg:
    """Lightweight stand-in for the merged ``YAMLConfig`` view."""

    def __init__(self, **overrides) -> None:
        defaults = dict(
            stop_loss_pct=1.5,
            take_profit_pct=2.0,
            momentum_exit_score=-0.03,
            max_hold_minutes=90.0,
            stale_position_min_pnl_pct=0.3,
            flatten_before_close_minutes=15.0,
        )
        defaults.update(overrides)
        for k, v in defaults.items():
            setattr(self, k, v)


class _RiskCfg:
    def __init__(self, *, stop_loss_pct: float | None = None,
                 take_profit_pct: float | None = None) -> None:
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct


class _Cfg:
    def __init__(self, exit_=None, risk_=None) -> None:
        self.exit = exit_ or _ExitCfg()
        self.risk = risk_ or _RiskCfg()


# ---------------------------------------------------------------------------
# 1) Individual rules — basic firing
# ---------------------------------------------------------------------------


def test_stop_loss_triggers_sell() -> None:
    position = _make_position(avg=100.0, market=98.4)
    result = stop_loss_exit(position, current_price=98.4, config=_Cfg())
    assert isinstance(result, ExitDecision)
    assert result.should_exit is True
    assert result.rule == "stop_loss"
    assert result.pnl_pct is not None and result.pnl_pct <= -1.5


def test_take_profit_triggers_sell() -> None:
    position = _make_position(avg=100.0, market=102.1)
    result = take_profit_exit(position, current_price=102.1, config=_Cfg())
    assert result.should_exit is True
    assert result.rule == "take_profit"
    assert result.pnl_pct >= 2.0


def test_momentum_exit_triggers_sell() -> None:
    position = _make_position()
    result = momentum_exit(position, opportunity_score=-0.05, config=_Cfg())
    assert result.should_exit is True
    assert result.rule == "momentum_exit"


def test_momentum_exit_holds_when_score_above_floor() -> None:
    position = _make_position()
    result = momentum_exit(position, opportunity_score=0.05, config=_Cfg())
    assert result.should_exit is False


def test_time_exit_triggers_when_stale_pnl_and_old() -> None:
    opened = (datetime.now(timezone.utc) - timedelta(minutes=120)).isoformat()
    position = _make_position(avg=100.0, market=100.1, opened_at=opened)
    result = time_exit(
        position,
        now=datetime.now(timezone.utc),
        config=_Cfg(),
    )
    assert result.should_exit is True
    assert result.rule == "time_exit"
    assert result.held_minutes is not None and result.held_minutes >= 90


def test_time_exit_skipped_when_no_opened_at() -> None:
    position = _make_position(opened_at=None)
    result = time_exit(position, now=datetime.now(timezone.utc), config=_Cfg())
    assert result.should_exit is False


def test_time_exit_skipped_when_pnl_already_winning() -> None:
    opened = (datetime.now(timezone.utc) - timedelta(minutes=200)).isoformat()
    # market = 101.0 → pnl = +1% > stale_position_min_pnl_pct (0.3)
    position = _make_position(avg=100.0, market=101.0, opened_at=opened)
    result = time_exit(position, now=datetime.now(timezone.utc), config=_Cfg())
    assert result.should_exit is False


def test_flatten_before_close_triggers_inside_window() -> None:
    # 2026-05-15 19:50 UTC = 15:50 ET → 10 minutes to close.
    now = datetime(2026, 5, 15, 19, 50, 0, tzinfo=timezone.utc)
    position = _make_position()
    result = flatten_before_close_exit(position, now=now, config=_Cfg())
    assert result.should_exit is True
    assert result.rule == "flatten_before_close"


def test_flatten_before_close_skipped_outside_window() -> None:
    # 13:00 UTC = 09:00 ET → before open; rule must not fire.
    now = datetime(2026, 5, 15, 13, 0, 0, tzinfo=timezone.utc)
    position = _make_position()
    result = flatten_before_close_exit(position, now=now, config=_Cfg())
    assert result.should_exit is False


# ---------------------------------------------------------------------------
# 2) No short — every rule requires an open long
# ---------------------------------------------------------------------------


def test_no_position_never_opens_a_short() -> None:
    none_pos = _make_position(quantity=0.0)
    cfg = _Cfg()
    now = datetime(2026, 5, 15, 19, 50, 0, tzinfo=timezone.utc)
    # Each rule is structurally inert without a long.
    assert stop_loss_exit(none_pos, 98.0, cfg).should_exit is False
    assert take_profit_exit(none_pos, 102.0, cfg).should_exit is False
    assert momentum_exit(none_pos, -1.0, cfg).should_exit is False
    assert time_exit(none_pos, now, cfg).should_exit is False
    assert flatten_before_close_exit(none_pos, now, cfg).should_exit is False
    # And the aggregator agrees.
    assert (
        evaluate_exit_rules(
            none_pos,
            current_price=98.0,
            opportunity_score=-1.0,
            now=now,
            config=cfg,
        ).should_exit
        is False
    )


# ---------------------------------------------------------------------------
# 3) Priority + aggregator behaviour
# ---------------------------------------------------------------------------


def test_evaluate_priorities_stop_loss_over_other_rules() -> None:
    # Stale + losing → stop-loss must win over time/momentum.
    opened = (datetime.now(timezone.utc) - timedelta(minutes=180)).isoformat()
    position = _make_position(avg=100.0, market=97.0, opened_at=opened)
    result = evaluate_exit_rules(
        position,
        current_price=97.0,
        opportunity_score=-0.20,
        now=datetime.now(timezone.utc),
        config=_Cfg(),
    )
    assert result.should_exit is True
    assert result.rule == "stop_loss"


def test_evaluate_no_exit_when_clean() -> None:
    opened = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    position = _make_position(avg=100.0, market=100.5, opened_at=opened)
    # 13:00 UTC = 09:00 ET premarket → flatten cannot fire, momentum is fine.
    now = datetime(2026, 5, 15, 13, 0, 0, tzinfo=timezone.utc)
    result = evaluate_exit_rules(
        position,
        current_price=100.5,
        opportunity_score=0.20,
        now=now,
        config=_Cfg(),
    )
    assert result.should_exit is False
    assert result.rule is None


# ---------------------------------------------------------------------------
# 4) Profile-level risk.stop_loss_pct overrides the exit.* fallback.
# ---------------------------------------------------------------------------


def test_profile_risk_overrides_exit_block() -> None:
    cfg = _Cfg(risk_=_RiskCfg(stop_loss_pct=0.5))
    position = _make_position(avg=100.0, market=99.3)  # pnl = -0.7%
    result = stop_loss_exit(position, current_price=99.3, config=cfg)
    # 0.5% override triggers, 1.5% default would not.
    assert result.should_exit is True
    assert result.rule == "stop_loss"
