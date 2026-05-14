"""Risk-manager tests.

Critical guarantee under test: a live order is impossible unless the triple
opt-in (TRADING_MODE=live, LIVE_TRADING=true, ALLOW_LIVE_ORDERS=true) is set.
"""

from __future__ import annotations

import pytest

from src import config as cfg
from src.risk import evaluate_risk
from src.schemas import EnsembleResult, Features, PortfolioSnapshot, StrategyVote


def _settings_with_env(monkeypatch, **overrides):
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    cfg.get_settings.cache_clear()
    return cfg.get_settings()


def _features(**kw) -> Features:
    base = dict(
        symbol="TSLAx",
        last_price=100.0,
        bid=99.95,
        ask=100.05,
        spread_bps=10.0,
        return_5m=0.005,
        return_15m=0.01,
        return_1h=0.02,
        volatility_15m=0.002,
        volatility_1h=0.003,
        high_1h=101.0,
        low_1h=99.0,
        distance_from_high_1h=0.001,
        distance_from_low_1h=0.02,
        volume_1h=2_000.0,
    )
    base.update(kw)
    return Features(**base)


def _ensemble(action="BUY", score=0.6, confidence=0.8) -> EnsembleResult:
    return EnsembleResult(
        final_score=score,
        action=action,
        confidence=confidence,
        suggested_size_usd=250.0,
        votes=[
            StrategyVote(name="momentum", score=0.7, confidence=0.8),
            StrategyVote(name="breakout", score=0.5, confidence=0.6),
            StrategyVote(name="mean_reversion", score=-0.1, confidence=0.2),
        ],
        regime="TRENDING_UP",
    )


def _empty_portfolio(equity=10_000.0) -> PortfolioSnapshot:
    return PortfolioSnapshot(cash_usd=equity, equity_usd=equity)


# ---------------------------------------------------------------------------
# Live trading is impossible without the triple opt-in.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        # Single flag set.
        {"TRADING_MODE": "live", "LIVE_TRADING": "false", "ALLOW_LIVE_ORDERS": "false"},
        {"TRADING_MODE": "dry_run", "LIVE_TRADING": "true", "ALLOW_LIVE_ORDERS": "false"},
        {"TRADING_MODE": "dry_run", "LIVE_TRADING": "false", "ALLOW_LIVE_ORDERS": "true"},
        # Two flags set.
        {"TRADING_MODE": "live", "LIVE_TRADING": "true", "ALLOW_LIVE_ORDERS": "false"},
        {"TRADING_MODE": "live", "LIVE_TRADING": "false", "ALLOW_LIVE_ORDERS": "true"},
        {"TRADING_MODE": "dry_run", "LIVE_TRADING": "true", "ALLOW_LIVE_ORDERS": "true"},
    ],
)
def test_live_blocked_without_triple_opt_in(monkeypatch, env):
    settings = _settings_with_env(monkeypatch, **env)
    result = evaluate_risk(
        ensemble=_ensemble(),
        features=_features(),
        portfolio=_empty_portfolio(),
        settings=settings,
        intended_mode="live",
    )
    assert result.approved is False
    assert result.blocked_for_live_flags is True
    assert any("triple opt-in" in r for r in result.reasons)


def test_live_allowed_with_full_triple_opt_in(monkeypatch):
    settings = _settings_with_env(
        monkeypatch,
        TRADING_MODE="live",
        LIVE_TRADING="true",
        ALLOW_LIVE_ORDERS="true",
    )
    result = evaluate_risk(
        ensemble=_ensemble(),
        features=_features(),
        portfolio=_empty_portfolio(),
        settings=settings,
        intended_mode="live",
    )
    assert result.approved is True
    assert result.blocked_for_live_flags is False


def test_dry_run_default_does_not_engage_live_gate(monkeypatch):
    settings = _settings_with_env(monkeypatch)  # defaults: dry_run + all flags off
    result = evaluate_risk(
        ensemble=_ensemble(),
        features=_features(),
        portfolio=_empty_portfolio(),
        settings=settings,
        intended_mode="dry_run",
    )
    assert result.approved is True
    assert result.blocked_for_live_flags is False


# ---------------------------------------------------------------------------
# Functional risk checks.
# ---------------------------------------------------------------------------


def test_blocked_when_confidence_below_threshold(monkeypatch):
    settings = _settings_with_env(monkeypatch)
    result = evaluate_risk(
        ensemble=_ensemble(confidence=0.1),
        features=_features(),
        portfolio=_empty_portfolio(),
        settings=settings,
    )
    assert result.approved is False
    assert any("confidence" in r for r in result.reasons)


def test_blocked_when_spread_too_high(monkeypatch):
    settings = _settings_with_env(monkeypatch)
    feats = _features(spread_bps=500.0)
    result = evaluate_risk(
        ensemble=_ensemble(),
        features=feats,
        portfolio=_empty_portfolio(),
        settings=settings,
    )
    assert result.approved is False
    assert any("spread" in r for r in result.reasons)


def test_blocked_when_unknown_symbol(monkeypatch):
    settings = _settings_with_env(monkeypatch)
    feats = _features(symbol="UNKNOWNx")
    result = evaluate_risk(
        ensemble=_ensemble(),
        features=feats,
        portfolio=_empty_portfolio(),
        settings=settings,
    )
    assert result.approved is False
    assert any("allowlist" in r or "not in allowlist" in r for r in result.reasons)


def test_blocked_when_exposure_exceeds_cap(monkeypatch):
    from src.schemas import Position

    settings = _settings_with_env(monkeypatch)
    cap = settings.config.risk.max_total_exposure_usd
    portfolio = PortfolioSnapshot(
        equity_usd=10_000.0,
        cash_usd=0.0,
        positions=[
            Position(
                symbol="TSLAx",
                quantity=1.0,
                avg_entry_price=cap,
                market_price=cap,
                notional_usd=cap,
            )
        ],
    )
    result = evaluate_risk(
        ensemble=_ensemble(),
        features=_features(),
        portfolio=portfolio,
        settings=settings,
    )
    assert result.approved is False
    assert any("exposure" in r for r in result.reasons)


def test_blocked_when_drawdown_breached(monkeypatch):
    settings = _settings_with_env(monkeypatch)
    starting = settings.config.competition.starting_equity_usd
    portfolio = PortfolioSnapshot(
        equity_usd=starting * 0.7,  # 30% drawdown
        cash_usd=starting * 0.7,
    )
    result = evaluate_risk(
        ensemble=_ensemble(),
        features=_features(),
        portfolio=portfolio,
        settings=settings,
    )
    assert result.approved is False
    assert any("drawdown" in r.lower() for r in result.reasons)
