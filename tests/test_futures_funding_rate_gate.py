"""Funding-rate gate for the futures engine.

The risk gate refuses a BUY when the symbol's per-hour funding rate exceeds
``futures.max_funding_rate_pct_per_hour`` (default 0.5%/h). SELL exits and
HOLDs are exempt: we always want to be able to flatten a losing position
even when funding spiked. The gate is no-op on the spot engine to preserve
backwards compatibility.
"""

from __future__ import annotations

import pytest

from src import config as cfg
from src.risk import evaluate_risk
from src.schemas import EnsembleResult, Features, PortfolioSnapshot, Position, StrategyVote


def _features(*, funding_rate: float | None = None, symbol: str = "AAPLx") -> Features:
    return Features(
        symbol=symbol,
        last_price=200.0,
        bid=199.90, ask=200.10, spread_bps=10.0,
        return_5m=0.001, return_15m=0.001, return_1h=0.001,
        volatility_15m=0.001, volatility_1h=0.001,
        high_1h=202.0, low_1h=198.0,
        distance_from_high_1h=0.01, distance_from_low_1h=0.01,
        volume_1h=5_000.0,
        mark_price=200.0,
        funding_rate_pct_per_hour=funding_rate,
    )


def _ensemble(action: str = "BUY") -> EnsembleResult:
    return EnsembleResult(
        final_score=0.5, action=action,  # type: ignore[arg-type]
        confidence=0.7, suggested_size_usd=10.0,
        votes=[StrategyVote(name="momentum", score=0.5, confidence=0.7)],
        regime="TRENDING_UP",
    )


def _settings_futures(monkeypatch):
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    # The profile already routes to engine=futures via YAML; assert it.
    assert s.config.execution.engine == "futures"
    return s


def _empty_portfolio(settings) -> PortfolioSnapshot:
    eq = settings.config.competition.starting_equity_usd
    return PortfolioSnapshot(cash_usd=eq, equity_usd=eq)


@pytest.mark.parametrize("funding_rate", [-0.10, 0.0, 0.10, 0.49])
def test_futures_buy_allowed_below_threshold(monkeypatch, funding_rate: float) -> None:
    settings = _settings_futures(monkeypatch)
    result = evaluate_risk(
        ensemble=_ensemble("BUY"),
        features=_features(funding_rate=funding_rate),
        portfolio=_empty_portfolio(settings),
        settings=settings,
    )
    funding_check = next(c for c in result.checks if c.name == "max_funding_rate")
    assert funding_check.passed is True
    assert result.approved is True


@pytest.mark.parametrize("funding_rate", [0.55, 1.0, 2.5, 5.0])
def test_futures_buy_refused_above_threshold(monkeypatch, funding_rate: float) -> None:
    settings = _settings_futures(monkeypatch)
    result = evaluate_risk(
        ensemble=_ensemble("BUY"),
        features=_features(funding_rate=funding_rate),
        portfolio=_empty_portfolio(settings),
        settings=settings,
    )
    funding_check = next(c for c in result.checks if c.name == "max_funding_rate")
    assert funding_check.passed is False
    assert result.approved is False
    assert any("funding rate" in r.lower() for r in result.reasons)


def test_futures_sell_exit_not_blocked_by_funding(monkeypatch) -> None:
    """SELL must be allowed even when funding rate is high — we still want
    to flatten a losing position."""
    settings = _settings_futures(monkeypatch)
    eq = settings.config.competition.starting_equity_usd
    # Hold a small long; portfolio equity at starting so drawdown stays calm.
    portfolio = PortfolioSnapshot(
        cash_usd=eq - 10.0, equity_usd=eq,
        positions=[
            Position(
                symbol="AAPLx", quantity=0.05,
                avg_entry_price=200.0, market_price=200.0,
                notional_usd=10.0,
            )
        ],
    )
    result = evaluate_risk(
        ensemble=_ensemble("SELL"),
        features=_features(funding_rate=10.0),
        portfolio=portfolio,
        settings=settings,
        is_exit_action=True,
    )
    funding_check = next(c for c in result.checks if c.name == "max_funding_rate")
    # Gate is inactive for SELL (says "gate inactive" in the detail).
    assert funding_check.passed is True
    assert "gate inactive" in funding_check.detail


def test_funding_gate_noop_on_spot_engine(monkeypatch) -> None:
    """Spot engine = no funding rate. The gate must short-circuit."""
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()
    assert settings.config.execution.engine == "spot"
    eq = settings.config.competition.starting_equity_usd
    # Even with an absurd funding rate, BUY passes because the gate is inactive.
    result = evaluate_risk(
        ensemble=_ensemble("BUY"),
        features=_features(funding_rate=99.0, symbol="TSLAx"),
        portfolio=PortfolioSnapshot(cash_usd=eq, equity_usd=eq),
        settings=settings,
    )
    funding_check = next(c for c in result.checks if c.name == "max_funding_rate")
    assert funding_check.passed is True
    assert "gate inactive" in funding_check.detail


def test_funding_gate_threshold_honors_config_override(monkeypatch) -> None:
    settings = _settings_futures(monkeypatch)
    # Tighten the cap to 0.2%/h. A 0.3%/h rate must now trigger.
    settings.config.futures.max_funding_rate_pct_per_hour = 0.2
    result = evaluate_risk(
        ensemble=_ensemble("BUY"),
        features=_features(funding_rate=0.3),
        portfolio=_empty_portfolio(settings),
        settings=settings,
    )
    funding_check = next(c for c in result.checks if c.name == "max_funding_rate")
    assert funding_check.passed is False
