"""Actionability gate regression tests.

These tests own the safety story behind the calibration phase:

- SELL is exit-only by default; shorting requires both env + YAML flags.
- BUY needs ``final_score >= min_opportunity_score_buy``.
- ``no_trade_if_negative_opportunity`` downgrades BUY when score < 0.
- Low liquidity dampens the suggested size but does not flip the action.
- The aggressive profile lowers thresholds **but never bypasses** the
  exit-only rule and never permits an implicit short.
"""

from __future__ import annotations

import pytest

from src import config as cfg
from src.actionability import apply_actionability_gates
from src.schemas import EnsembleResult, Features, Position, StrategyVote


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


def _ensemble(action: str, score: float, *, suggested: float = 500.0, conf: float = 0.6) -> EnsembleResult:
    return EnsembleResult(
        final_score=score,
        action=action,  # type: ignore[arg-type]
        confidence=conf,
        suggested_size_usd=suggested,
        votes=[StrategyVote(name="momentum", score=score, confidence=conf)],
        regime="TRENDING_UP",
        rationale="test",
    )


def _settings(monkeypatch, *, profile: str = "balanced", env: dict[str, str] | None = None) -> cfg.Settings:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", profile)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    cfg.get_settings.cache_clear()
    return cfg.get_settings()


def test_buy_below_threshold_becomes_hold(monkeypatch) -> None:
    s = _settings(monkeypatch)
    ensemble = _ensemble("BUY", score=0.10)  # < default min_buy=0.18
    new, info = apply_actionability_gates(
        ensemble=ensemble, features=_features(),
        position=None, liquidity_score=0.8, settings=s,
    )
    assert new.action == "HOLD"
    assert info.buy_eligible is False
    assert "below_buy_threshold" in info.reason


def test_buy_above_threshold_stays_buy(monkeypatch) -> None:
    s = _settings(monkeypatch)
    ensemble = _ensemble("BUY", score=0.40)
    new, info = apply_actionability_gates(
        ensemble=ensemble, features=_features(),
        position=None, liquidity_score=0.8, settings=s,
    )
    assert new.action == "BUY"
    assert info.buy_eligible is True


def test_no_trade_on_negative_opportunity_blocks_buy(monkeypatch) -> None:
    s = _settings(monkeypatch)
    # action=BUY but score is negative — shouldn't normally occur, but the
    # defensive gate must catch it.
    ensemble = _ensemble("BUY", score=-0.05)
    new, info = apply_actionability_gates(
        ensemble=ensemble, features=_features(),
        position=None, liquidity_score=0.8, settings=s,
    )
    assert new.action == "HOLD"
    assert "negative_opportunity" in info.reason or "below_buy_threshold" in info.reason


def test_sell_without_position_is_blocked_by_default(monkeypatch) -> None:
    s = _settings(monkeypatch)
    ensemble = _ensemble("SELL", score=-0.40)
    new, info = apply_actionability_gates(
        ensemble=ensemble, features=_features(),
        position=None, liquidity_score=0.8, settings=s,
    )
    assert new.action == "HOLD"
    assert info.reason == "sell_without_position_shorting_disabled"
    assert info.sell_eligible is False


def test_sell_with_open_position_is_allowed_and_size_clamped(monkeypatch) -> None:
    s = _settings(monkeypatch)
    ensemble = _ensemble("SELL", score=-0.40, suggested=10_000.0)
    position = Position(
        symbol="AAPLx", quantity=2.0, avg_entry_price=90.0,
        market_price=100.0, notional_usd=200.0,
    )
    new, info = apply_actionability_gates(
        ensemble=ensemble, features=_features(last=100.0),
        position=position, liquidity_score=0.8, settings=s,
    )
    assert new.action == "SELL"
    assert info.sell_eligible is True
    # 2 units × $100 ⇒ max notional 200, so the 10k size is clamped.
    assert new.suggested_size_usd == pytest.approx(200.0)


def test_low_liquidity_dampens_size_without_flipping_action(monkeypatch) -> None:
    s = _settings(monkeypatch)
    ensemble = _ensemble("BUY", score=0.40, suggested=1000.0)
    new, info = apply_actionability_gates(
        ensemble=ensemble, features=_features(),
        position=None, liquidity_score=0.2, settings=s,  # below default 0.5
    )
    assert new.action == "BUY"
    assert info.size_dampened is True
    # default factor is 0.5
    assert new.suggested_size_usd == pytest.approx(500.0)


def test_aggressive_profile_lowers_buy_threshold_but_still_no_short(monkeypatch) -> None:
    s = _settings(monkeypatch, profile="aggressive_competition")
    # Below the *balanced* threshold but above aggressive (0.18 vs lower).
    # Aggressive profile still uses the trading.min_opportunity_score_buy
    # default unless overridden — we set the env to lower it explicitly.
    monkeypatch.setenv("MIN_OPPORTUNITY_SCORE_BUY", "0.10")
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    buy_above_low = apply_actionability_gates(
        ensemble=_ensemble("BUY", score=0.12),
        features=_features(),
        position=None,
        liquidity_score=0.8,
        settings=s,
    )[0]
    assert buy_above_low.action == "BUY"

    # Still no shorting allowed.
    sell_no_pos = apply_actionability_gates(
        ensemble=_ensemble("SELL", score=-0.40),
        features=_features(),
        position=None,
        liquidity_score=0.8,
        settings=s,
    )[1]
    assert sell_no_pos.reason == "sell_without_position_shorting_disabled"


def test_shorting_requires_both_env_and_config_flags(monkeypatch) -> None:
    # Only env set → still off (YAML default is False).
    monkeypatch.setenv("SHORTING_ENABLED", "true")
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    new, info = apply_actionability_gates(
        ensemble=_ensemble("SELL", score=-0.40),
        features=_features(),
        position=None,
        liquidity_score=0.8,
        settings=s,
    )
    assert new.action == "HOLD"
    assert info.reason == "sell_without_position_shorting_disabled"


def test_sell_below_sell_threshold_becomes_hold(monkeypatch) -> None:
    s = _settings(monkeypatch)
    # |score| 0.10 < default min_sell 0.18 → HOLD even with an open position.
    pos = Position(symbol="AAPLx", quantity=2.0, avg_entry_price=90.0,
                   market_price=100.0, notional_usd=200.0)
    ensemble = _ensemble("SELL", score=-0.10)
    new, info = apply_actionability_gates(
        ensemble=ensemble, features=_features(),
        position=pos, liquidity_score=0.8, settings=s,
    )
    assert new.action == "HOLD"
    assert "below_sell_threshold" in info.reason


def test_env_override_for_buy_threshold(monkeypatch) -> None:
    monkeypatch.setenv("MIN_OPPORTUNITY_SCORE_BUY", "0.30")
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    # Score 0.20 is above the YAML default 0.18 but below the env-overridden 0.30.
    new, _ = apply_actionability_gates(
        ensemble=_ensemble("BUY", score=0.20),
        features=_features(),
        position=None,
        liquidity_score=0.8,
        settings=s,
    )
    assert new.action == "HOLD"
