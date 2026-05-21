"""Smoke tests: live trading remains explicit opt-in end-to-end.

These tests mock the Kraken CLI — no real orders are sent.
"""

from __future__ import annotations

import pytest

from src import config as cfg
from src import execution, kraken_cli
from src.risk import evaluate_risk
from src.schemas import (
    EnsembleResult,
    Features,
    PortfolioSnapshot,
    RiskCheck,
    RiskResult,
    StrategyVote,
)


def _features(symbol: str = "AAPLx", price: float = 200.0) -> Features:
    return Features(
        symbol=symbol,
        last_price=price,
        bid=price - 0.10,
        ask=price + 0.10,
        spread_bps=10.0,
        return_5m=0.001,
        return_15m=0.001,
        return_1h=0.001,
        volatility_15m=0.001,
        volatility_1h=0.001,
        high_1h=price * 1.01,
        low_1h=price * 0.99,
        distance_from_high_1h=0.01,
        distance_from_low_1h=0.01,
        volume_1h=5_000.0,
        mark_price=price,
        funding_rate_pct_per_hour=0.0,
    )


def _ensemble(action: str = "BUY", size_usd: float = 25.0) -> EnsembleResult:
    return EnsembleResult(
        final_score=0.5,
        action=action,  # type: ignore[arg-type]
        confidence=0.7,
        suggested_size_usd=size_usd,
        votes=[StrategyVote(name="momentum", score=0.5, confidence=0.7)],
        regime="TRENDING_UP",
    )


def _empty_portfolio(equity: float = 10_000.0) -> PortfolioSnapshot:
    return PortfolioSnapshot(cash_usd=equity, equity_usd=equity)


def _risk_approved(size_usd: float = 25.0) -> RiskResult:
    return RiskResult(
        approved=True,
        reasons=[],
        checks=[RiskCheck(name="dummy", passed=True, detail="fixture")],
        adjusted_size_usd=size_usd,
        blocked_for_live_flags=False,
    )


@pytest.mark.parametrize(
    "env",
    [
        {"TRADING_MODE": "live", "LIVE_TRADING": "false", "ALLOW_LIVE_ORDERS": "false"},
        {"TRADING_MODE": "live", "LIVE_TRADING": "true", "ALLOW_LIVE_ORDERS": "false"},
    ],
)
def test_risk_blocks_live_without_full_triple_opt_in(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    cfg.get_settings.cache_clear()

    result = evaluate_risk(
        ensemble=_ensemble(),
        features=_features(),
        portfolio=_empty_portfolio(),
        settings=cfg.get_settings(),
        intended_mode="live",
    )
    assert result.approved is False
    assert result.blocked_for_live_flags is True
    assert any("triple opt-in" in r for r in result.reasons)

    cfg.get_settings.cache_clear()


def test_spot_execute_blocks_live_without_triple_opt_in_before_cli(monkeypatch):
    """Execution re-validates live flags even if risk were wrongly approved."""
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "false")
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "aggressive_competition")
    cfg.get_settings.cache_clear()

    def fail(*a, **kw):
        pytest.fail("live spot must not reach kraken_cli without full triple opt-in")

    monkeypatch.setattr(kraken_cli, "place_order", fail)
    monkeypatch.setattr(kraken_cli, "validate_live_order", fail)

    result = execution.execute(
        features=_features("NVDAx", price=940.0),
        ensemble=_ensemble("BUY", size_usd=25.0),
        risk=_risk_approved(25.0),
    )
    assert result.status == "blocked"
    assert "triple opt-in" in (result.error or "")

    cfg.get_settings.cache_clear()
