"""``exit_rules.flatten_before_close_exit`` must fire on futures positions too.

The deterministic exit-rules engine is engine-agnostic by construction
(it inspects ``Position`` schemas without caring about spot vs futures),
but we pin the regression here because the futures pivot rests on
"flatten 15 minutes before US_CORE close" to avoid overnight funding
accrual.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src import config as cfg
from src.exit_rules import (
    evaluate_exit_rules,
    flatten_before_close_exit,
)
from src.schemas import Position


def _position(quantity: float = 0.05, avg_entry: float = 200.0) -> Position:
    return Position(
        symbol="AAPLx",
        quantity=quantity,
        avg_entry_price=avg_entry,
        market_price=avg_entry,
        notional_usd=quantity * avg_entry,
    )


@pytest.fixture()
def futures_profile(monkeypatch):
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    cfg.get_settings.cache_clear()
    yield cfg.get_settings()
    cfg.get_settings.cache_clear()


def test_flatten_before_close_fires_15_min_before_us_core_close(
    futures_profile,
) -> None:
    """US_CORE closes at 16:00 ET = 20:00 UTC in DST. 19:50 UTC → 10 min left.
    The rule must fire (cap is 15 min). Use a Wednesday so weekday gating
    passes."""
    now = datetime(2026, 5, 13, 19, 50, tzinfo=timezone.utc)
    pos = _position()
    pos = pos.model_copy(update={"opened_at": "2026-05-13T18:00:00Z"})
    decision = flatten_before_close_exit(pos, now, futures_profile.config)
    assert decision.should_exit is True
    assert decision.rule == "flatten_before_close"


def test_flatten_before_close_silent_when_outside_us_core(
    futures_profile,
) -> None:
    # Saturday — US_CORE window is closed entirely.
    now = datetime(2026, 5, 16, 19, 50, tzinfo=timezone.utc)
    pos = _position()
    pos = pos.model_copy(update={"opened_at": "2026-05-16T18:00:00Z"})
    decision = flatten_before_close_exit(pos, now, futures_profile.config)
    assert decision.should_exit is False


def test_flatten_before_close_never_opens_short_on_zero_qty(
    futures_profile,
) -> None:
    """The rule must not fire when we hold no long — protects against
    accidental short."""
    now = datetime(2026, 5, 13, 19, 50, tzinfo=timezone.utc)
    pos = _position(quantity=0.0)
    pos = pos.model_copy(update={"opened_at": "2026-05-13T18:00:00Z"})
    decision = flatten_before_close_exit(pos, now, futures_profile.config)
    assert decision.should_exit is False


def test_evaluate_exit_rules_picks_flatten_before_close(
    futures_profile,
) -> None:
    """Aggregate priority: SL/TP/momentum/time/flatten. With benign price
    and a fresh entry, the only rule that should fire near close is
    flatten_before_close."""
    now = datetime(2026, 5, 13, 19, 55, tzinfo=timezone.utc)
    pos = _position(quantity=0.05, avg_entry=200.0)
    # Open 30 minutes ago: no SL/TP (same price), no time_exit (max_hold=90).
    pos = pos.model_copy(update={"opened_at": "2026-05-13T19:25:00Z"})
    decision = evaluate_exit_rules(
        position=pos,
        current_price=200.0,
        opportunity_score=0.10,  # above momentum-exit floor
        now=now,
        config=futures_profile.config,
    )
    assert decision.should_exit is True
    assert decision.rule == "flatten_before_close"
