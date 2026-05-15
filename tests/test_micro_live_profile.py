"""micro_live_100eur profile contract tests.

Guarantees:
- The profile exists in the example YAML and merges correctly.
- ``max_total_exposure_usd`` <= 30 (the user's hard ceiling).
- ``max_position_notional_usd`` <= 10.
- Shorting stays disabled.
- The triple opt-in for live trading is still enforced when the profile
  is active (the profile NEVER bypasses the gate).
"""

from __future__ import annotations

import pytest

from src import config as cfg
from src.risk import evaluate_risk
from src.schemas import EnsembleResult, Features, PortfolioSnapshot, StrategyVote


PROFILE = "micro_live_100eur"


def _features() -> Features:
    return Features(
        symbol="AAPLx",
        last_price=100.0,
        bid=99.95,
        ask=100.05,
        spread_bps=5.0,
        return_5m=0.001,
        return_15m=0.001,
        return_1h=0.002,
        volatility_15m=0.0015,
        volatility_1h=0.0020,
        high_1h=102.0,
        low_1h=98.0,
        distance_from_high_1h=0.02,
        distance_from_low_1h=0.01,
        volume_1h=2000.0,
    )


def _ensemble(action: str = "BUY", score: float = 0.5) -> EnsembleResult:
    return EnsembleResult(
        final_score=score,
        action=action,  # type: ignore[arg-type]
        confidence=0.6,
        suggested_size_usd=10.0,
        votes=[StrategyVote(name="momentum", score=score, confidence=0.6)],
        regime="TRENDING_UP",
        rationale="test",
    )


def test_micro_live_profile_listed_in_available(monkeypatch) -> None:
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    assert PROFILE in s.available_profiles


def test_micro_live_profile_caps_30_usd(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", PROFILE)
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    assert s.active_profile == PROFILE
    assert s.config.risk.max_total_exposure_usd <= 30.0
    assert s.config.risk.max_position_notional_usd <= 10.0
    assert s.config.trading.shorting_enabled is False


def test_micro_live_profile_still_requires_triple_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", PROFILE)
    # Force only PART of the triple opt-in. Live trade must remain blocked.
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "false")
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()

    result = evaluate_risk(
        ensemble=_ensemble(),
        features=_features(),
        portfolio=PortfolioSnapshot(cash_usd=100.0, equity_usd=100.0),
        settings=s,
        intended_mode="live",
    )
    assert result.approved is False
    assert result.blocked_for_live_flags is True
    assert any("triple opt-in" in r for r in result.reasons)


def test_micro_live_profile_exit_block_caps(monkeypatch) -> None:
    """The risk-level stop/take overrides surface to the exit engine."""
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", PROFILE)
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    # The profile sets stop_loss_pct=1.5 / take_profit_pct=2.0.
    assert s.config.risk.stop_loss_pct == pytest.approx(1.5)
    assert s.config.risk.take_profit_pct == pytest.approx(2.0)
