"""Session-guard tests.

Verifies that:
- ``sessions.is_entry_allowed`` follows the US_CORE / PREMARKET /
  AFTERHOURS / OVERNIGHT / WEEKEND boundaries.
- ``main._apply_exit_rules_and_session_guard`` downgrades a BUY intent
  to HOLD outside the allowed sessions while leaving SELL exits alone.
- Empty ``allowed_entry_sessions`` disables the guard.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import config as cfg
from src import main as main_mod
from src.schemas import Actionability, EnsembleResult, Features, Position, StrategyVote
from src.sessions import MarketSession, current_session, is_entry_allowed


def _features(symbol: str = "AAPLx", last: float = 100.0) -> Features:
    return Features(
        symbol=symbol,
        last_price=last,
        bid=last - 0.05,
        ask=last + 0.05,
        spread_bps=5.0,
        return_5m=0.001,
        return_15m=0.001,
        return_1h=0.002,
        volatility_15m=0.0015,
        volatility_1h=0.0020,
        high_1h=last * 1.02,
        low_1h=last * 0.98,
        distance_from_high_1h=0.02,
        distance_from_low_1h=0.01,
        volume_1h=5000.0,
        source="test",
    )


def _ensemble(action: str, score: float = 0.4) -> EnsembleResult:
    return EnsembleResult(
        final_score=score,
        action=action,  # type: ignore[arg-type]
        confidence=0.6,
        suggested_size_usd=200.0,
        votes=[StrategyVote(name="momentum", score=score, confidence=0.6)],
        regime="TRENDING_UP",
        rationale="test",
    )


def _act(reason: str = "buy_eligible") -> Actionability:
    return Actionability(buy_eligible=True, reason=reason)


# ---------------------------------------------------------------------------
# 1) Sessions helper.
# ---------------------------------------------------------------------------


def test_is_entry_allowed_us_core() -> None:
    ts = datetime(2026, 5, 15, 14, 0, 0, tzinfo=timezone.utc)  # 10:00 ET
    ok, session = is_entry_allowed(["US_CORE"], now=ts)
    assert ok is True
    assert session == MarketSession.US_CORE


def test_is_entry_allowed_premarket_blocks_us_core_only() -> None:
    ts = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)  # 08:00 ET
    ok, session = is_entry_allowed(["US_CORE"], now=ts)
    assert ok is False
    assert session == MarketSession.US_PREMARKET


def test_is_entry_allowed_empty_list_disables_guard() -> None:
    ts = datetime(2026, 5, 16, 18, 0, 0, tzinfo=timezone.utc)  # weekend
    ok, session = is_entry_allowed([], now=ts)
    assert ok is True
    assert session == MarketSession.WEEKEND


# ---------------------------------------------------------------------------
# 2) Main-loop wiring — BUY blocked outside session, SELL exits allowed.
# ---------------------------------------------------------------------------


def test_buy_blocked_outside_allowed_session(monkeypatch) -> None:
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()

    # Force the "current" session to PREMARKET by monkeypatching the helper
    # main_mod uses (it imports ``is_entry_allowed`` from src.sessions).
    monkeypatch.setattr(
        main_mod,
        "is_entry_allowed",
        lambda allowed, now=None: (False, MarketSession.US_PREMARKET),
    )

    ens = _ensemble("BUY")
    act = _act("buy_eligible")
    new_ens, new_act = main_mod._apply_exit_rules_and_session_guard(
        ensemble=ens,
        actionability=act,
        feats=_features(),
        open_position=None,
        settings=settings,
    )
    assert new_ens.action == "HOLD"
    assert "buy_blocked_outside_session" in new_act.reason


def test_sell_exit_allowed_outside_entry_session(monkeypatch) -> None:
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()

    monkeypatch.setattr(
        main_mod,
        "is_entry_allowed",
        lambda allowed, now=None: (False, MarketSession.US_PREMARKET),
    )

    ens = _ensemble("SELL", score=-0.4)
    act = Actionability(sell_eligible=True, reason="sell_exit")
    pos = Position(
        symbol="AAPLx",
        quantity=2.0,
        avg_entry_price=100.0,
        market_price=100.0,
        notional_usd=200.0,
    )
    new_ens, new_act = main_mod._apply_exit_rules_and_session_guard(
        ensemble=ens,
        actionability=act,
        feats=_features(),
        open_position=pos,
        settings=settings,
    )
    # SELL exits are not gated by the session guard.
    assert new_ens.action == "SELL"
    assert new_act.sell_eligible is True


def test_buy_allowed_in_core_session_passes_through(monkeypatch) -> None:
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()
    monkeypatch.setattr(
        main_mod,
        "is_entry_allowed",
        lambda allowed, now=None: (True, MarketSession.US_CORE),
    )
    ens = _ensemble("BUY")
    act = _act("buy_eligible")
    new_ens, new_act = main_mod._apply_exit_rules_and_session_guard(
        ensemble=ens,
        actionability=act,
        feats=_features(),
        open_position=None,
        settings=settings,
    )
    assert new_ens.action == "BUY"
    assert new_act.reason == "buy_eligible"


def test_exit_rule_converts_buy_to_sell_with_rule_in_actionability(monkeypatch) -> None:
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()
    monkeypatch.setattr(
        main_mod,
        "is_entry_allowed",
        lambda allowed, now=None: (True, MarketSession.US_CORE),
    )
    pos = Position(
        symbol="AAPLx",
        quantity=2.0,
        avg_entry_price=100.0,
        market_price=97.0,  # -3% pnl → triggers stop_loss
        notional_usd=194.0,
    )
    # Use a HOLD intent: even without a BUY/SELL the exit must fire.
    ens = _ensemble("HOLD", score=0.05)
    act = Actionability(reason="hold")
    new_ens, new_act = main_mod._apply_exit_rules_and_session_guard(
        ensemble=ens,
        actionability=act,
        feats=_features(last=97.0),
        open_position=pos,
        settings=settings,
    )
    assert new_ens.action == "SELL"
    # SELL size is clamped to the open notional (2 * 97 = 194).
    assert new_ens.suggested_size_usd == pytest.approx(194.0)
    assert new_act.reason.startswith("exit_rule_stop_loss")
