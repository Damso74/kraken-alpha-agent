"""Leverage cap regression tests for the futures pivot.

Intransigeant rule under test: the risk gate refuses any leverage value
strictly above ``HARDCODED_MAX_LEVERAGE`` (= 1.0). The check covers three
attack surfaces:

1. ``intended_leverage`` kwarg (caller override).
2. ``futures.max_leverage`` config knob.
3. Wrapper-level ``_build_order_args`` guard (defence in depth).

If any of these can route a leverage > 1.0 the bot is no longer
"spot-equivalent" and the override is broken.
"""

from __future__ import annotations

import pytest

from src import config as cfg
from src.risk import HARDCODED_MAX_LEVERAGE, evaluate_risk
from src.schemas import EnsembleResult, Features, PortfolioSnapshot, StrategyVote
from src.futures_kraken_cli import _build_order_args


def _features(symbol: str = "AAPLx") -> Features:
    return Features(
        symbol=symbol,
        last_price=200.0,
        bid=199.90, ask=200.10, spread_bps=10.0,
        return_5m=0.001, return_15m=0.002, return_1h=0.003,
        volatility_15m=0.001, volatility_1h=0.002,
        high_1h=202.0, low_1h=198.0,
        distance_from_high_1h=0.01, distance_from_low_1h=0.01,
        volume_1h=5_000.0,
        mark_price=200.0,
        funding_rate_pct_per_hour=0.0,
    )


def _ensemble(action: str = "BUY") -> EnsembleResult:
    return EnsembleResult(
        final_score=0.5, action=action,  # type: ignore[arg-type]
        confidence=0.7, suggested_size_usd=10.0,
        votes=[StrategyVote(name="momentum", score=0.6, confidence=0.7)],
        regime="TRENDING_UP",
    )


def test_hardcoded_max_leverage_constant_is_one() -> None:
    """The whole pivot rests on this constant. If it ever drifts, fail loudly."""
    assert HARDCODED_MAX_LEVERAGE == 1.0


def _empty_portfolio(settings) -> PortfolioSnapshot:
    """Portfolio at starting equity so the drawdown gate is silent."""
    eq = settings.config.competition.starting_equity_usd
    return PortfolioSnapshot(cash_usd=eq, equity_usd=eq)


def test_leverage_default_is_approved(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()
    result = evaluate_risk(
        ensemble=_ensemble(), features=_features(),
        portfolio=_empty_portfolio(settings),
        settings=settings,
    )
    leverage_check = next(c for c in result.checks if c.name == "max_leverage")
    assert leverage_check.passed is True
    assert result.approved is True


@pytest.mark.parametrize("requested", [1.01, 2.0, 3.5, 10.0, 100.0])
def test_caller_override_above_one_is_refused(monkeypatch, requested: float) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()
    result = evaluate_risk(
        ensemble=_ensemble(), features=_features(),
        portfolio=_empty_portfolio(settings),
        settings=settings,
        intended_leverage=requested,
    )
    leverage_check = next(c for c in result.checks if c.name == "max_leverage")
    assert leverage_check.passed is False, (
        f"risk gate must refuse leverage={requested} but check passed"
    )
    assert result.approved is False
    assert any("leverage" in r.lower() for r in result.reasons), result.reasons


def test_config_max_leverage_above_one_is_refused(monkeypatch) -> None:
    """A YAML drift bumping ``futures.max_leverage`` above 1.0 must NOT
    relax the gate. The hardcoded ceiling wins."""
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()
    # Simulate a config drift.
    settings.config.futures.max_leverage = 5.0
    result = evaluate_risk(
        ensemble=_ensemble(), features=_features(),
        portfolio=_empty_portfolio(settings),
        settings=settings,
    )
    leverage_check = next(c for c in result.checks if c.name == "max_leverage")
    assert leverage_check.passed is False
    assert result.approved is False
    assert any("hardcoded cap" in r.lower() for r in result.reasons)


def test_wrapper_refuses_leverage_above_one() -> None:
    """Belt-and-suspenders: the CLI wrapper also raises if a buggy caller
    somehow bypasses the risk gate."""
    with pytest.raises(ValueError, match="exceeds wrapper-level cap"):
        _build_order_args(
            side="buy", symbol="PF_AAPLXUSD", size=0.01,
            order_type="market", leverage=2.0, paper=True,
        )
