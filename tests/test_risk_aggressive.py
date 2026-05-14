"""The aggressive profile must NEVER bypass the live triple opt-in.

This is the most important regression test for the competition phase: a
profile change is allowed to loosen risk thresholds, but it must keep the
live trading guardrails fully intact.
"""

from __future__ import annotations

from src import config as cfg
from src import risk as risk_mod
from src.schemas import (
    EnsembleResult,
    Features,
    PortfolioSnapshot,
    StrategyVote,
)


def _features(symbol: str = "AAPLx") -> Features:
    return Features(
        symbol=symbol,
        last_price=100.0,
        bid=99.95,
        ask=100.05,
        spread_bps=5.0,
        return_5m=0.01,
        return_15m=0.01,
        return_1h=0.02,
        volatility_15m=0.002,
        volatility_1h=0.002,
        high_1h=102.0,
        low_1h=99.0,
        distance_from_high_1h=0.02,
        distance_from_low_1h=0.01,
        volume_1h=5000.0,
        source="test",
    )


def _ensemble(action: str = "BUY", score: float = 0.5, conf: float = 0.85) -> EnsembleResult:
    return EnsembleResult(
        final_score=score,
        action=action,
        confidence=conf,
        suggested_size_usd=500.0,
        votes=[StrategyVote(name="momentum", score=score, confidence=conf)],
        regime="TRENDING_UP",
        rationale="test",
    )


def _empty_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(equity_usd=10_000.0, cash_usd=10_000.0, positions=[])


def test_aggressive_profile_allows_more_but_still_blocks_live_without_flags(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "aggressive_competition")
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "false")
    cfg.get_settings.cache_clear()
    risk_mod.reset_cooldowns()
    settings = cfg.get_settings()
    assert settings.active_profile == "aggressive_competition"

    result = risk_mod.evaluate_risk(
        ensemble=_ensemble(),
        features=_features(),
        portfolio=_empty_portfolio(),
        settings=settings,
        intended_mode="live",
    )
    assert result.approved is False
    assert result.blocked_for_live_flags is True
    assert any("triple opt-in" in r for r in result.reasons)


def test_aggressive_profile_with_full_opt_in_passes_in_paper_mode(monkeypatch) -> None:
    """Aggressive thresholds approve a high-conviction trade in paper mode."""
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "aggressive_competition")
    monkeypatch.setenv("TRADING_MODE", "paper")
    cfg.get_settings.cache_clear()
    risk_mod.reset_cooldowns()
    settings = cfg.get_settings()

    result = risk_mod.evaluate_risk(
        ensemble=_ensemble(score=0.6, conf=0.8),
        features=_features(),
        portfolio=_empty_portfolio(),
        settings=settings,
        intended_mode="paper",
    )
    # paper is not gated by the triple opt-in
    assert result.blocked_for_live_flags is False
    assert result.approved is True


def test_conservative_profile_blocks_low_confidence(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "conservative_debug")
    monkeypatch.setenv("TRADING_MODE", "paper")
    cfg.get_settings.cache_clear()
    risk_mod.reset_cooldowns()
    settings = cfg.get_settings()

    result = risk_mod.evaluate_risk(
        ensemble=_ensemble(score=0.35, conf=0.30),  # below 0.45 confidence
        features=_features(),
        portfolio=_empty_portfolio(),
        settings=settings,
        intended_mode="paper",
    )
    assert result.approved is False
    assert any("confidence" in r.lower() for r in result.reasons)
