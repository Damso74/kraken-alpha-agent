"""Regression tests for the exit-only SELL carve-out in :func:`evaluate_risk`.

Context: before the hotfix, gate 8 (``max_total_exposure``) checked the
symmetric inequality ``current_exposure + adjusted <= cap`` regardless of
whether the order was a fresh BUY or an exit-rule-triggered SELL. As a
consequence, once the agent had filled enough longs to saturate the
per-account exposure ceiling, every SELL exit was rejected with
``exposure ... would exceed cap ...`` — exactly when an exit is most
needed. The hotfix carves out ``is_exit_action=True AND action=="SELL"``
from gate 8 (and bypasses the per-position notional cap for the SELL leg
so a 44 USD position can be flattened in one shot instead of partial
25 USD slices). The no-short safety is enforced downstream by
``src.execution._execute_futures`` (and by the actionability layer for
the spot engine), so the carve-out cannot create a negative position.

The four tests below pin the contract:

1. SELL exit is approved at ``current_exposure == max_total_exposure``.
2. SELL exit is approved at ``open_positions_count == max_open_positions``
   (this was already true via gate 7 — kept as a regression).
3. A fresh BUY remains BLOCKED with ``over_exposure`` at the same
   saturation point.
4. The risk gate's approval of an exit-SELL on an *empty* portfolio does
   NOT result in a short, because the downstream futures execution layer
   refuses SELL without an open long.
"""

from __future__ import annotations

from src import config as cfg
from src import execution as execution_mod
from src.risk import evaluate_risk
from src.schemas import (
    EnsembleResult,
    Features,
    PortfolioSnapshot,
    Position,
    StrategyVote,
)


def _settings_with_env(monkeypatch, **overrides):
    for k, v in overrides.items():
        monkeypatch.setenv(k, v)
    cfg.get_settings.cache_clear()
    return cfg.get_settings()


def _features(symbol: str = "TSLAx", *, mark_price: float | None = None) -> Features:
    return Features(
        symbol=symbol,
        last_price=100.0,
        bid=99.95,
        ask=100.05,
        spread_bps=5.0,
        return_5m=0.005,
        return_15m=0.01,
        return_1h=0.02,
        volatility_15m=0.002,
        volatility_1h=0.003,
        high_1h=101.0,
        low_1h=99.0,
        distance_from_high_1h=0.001,
        distance_from_low_1h=0.02,
        volume_1h=5_000.0,
        mark_price=mark_price,
    )


def _ensemble(action: str = "BUY", confidence: float = 0.8, size_usd: float = 25.0) -> EnsembleResult:
    return EnsembleResult(
        final_score=0.5 if action == "BUY" else -0.5,
        action=action,
        confidence=confidence,
        suggested_size_usd=size_usd,
        votes=[
            StrategyVote(name="momentum", score=0.5, confidence=confidence),
        ],
        regime="TRENDING_UP",
    )


def _saturated_portfolio(symbol: str, cap: float) -> PortfolioSnapshot:
    """Return a portfolio with a single long worth ``cap`` USD (exposure==cap)."""
    return PortfolioSnapshot(
        equity_usd=10_000.0,
        cash_usd=0.0,
        positions=[
            Position(
                symbol=symbol,
                quantity=1.0,
                avg_entry_price=cap,
                market_price=cap,
                notional_usd=cap,
            )
        ],
    )


def test_sell_exit_approved_when_exposure_saturated(monkeypatch) -> None:
    """Gate 8 carve-out: an exit-SELL must pass even at the exposure ceiling."""
    settings = _settings_with_env(monkeypatch)
    cap = settings.config.risk.max_total_exposure_usd
    portfolio = _saturated_portfolio("TSLAx", cap)

    result = evaluate_risk(
        ensemble=_ensemble(action="SELL", size_usd=cap),
        features=_features(),
        portfolio=portfolio,
        settings=settings,
        is_exit_action=True,
    )

    assert result.approved is True, result.reasons
    assert not any("exposure" in r for r in result.reasons)
    detail = next(c.detail for c in result.checks if c.name == "max_total_exposure")
    assert "sell_exit bypasses cap" in detail


def test_sell_exit_approved_when_open_positions_saturated(monkeypatch) -> None:
    """Gate 7 already allows SELL when open_positions_count >= max_open_positions.

    Pinned as a regression to ensure the carve-out keeps coexisting with
    the exposure-cap carve-out (both must fire together for the exit path
    to flatten on a saturated portfolio).
    """
    settings = _settings_with_env(monkeypatch)
    cap = settings.config.risk.max_total_exposure_usd
    max_open = settings.config.risk.max_open_positions
    # Pick real xStocks tickers from the allowlist so gate 1 stays green.
    pool = ["TSLAx", "AAPLx", "NVDAx", "QQQx", "SPYx", "MSTRx", "CRCLx", "HOODx", "GLDx", "GOOGLx"]
    symbols = pool[:max_open]

    positions = [
        Position(
            symbol=sym,
            quantity=1.0,
            avg_entry_price=cap / max_open,
            market_price=cap / max_open,
            notional_usd=cap / max_open,
        )
        for sym in symbols
    ]
    portfolio = PortfolioSnapshot(equity_usd=10_000.0, cash_usd=0.0, positions=positions)

    result = evaluate_risk(
        ensemble=_ensemble(action="SELL", size_usd=cap / max_open),
        features=_features(symbol=symbols[0]),
        portfolio=portfolio,
        settings=settings,
        is_exit_action=True,
    )

    pos_check = next(c for c in result.checks if c.name == "max_open_positions")
    assert pos_check.passed is True
    assert result.approved is True, result.reasons


def test_buy_still_blocked_when_exposure_saturated(monkeypatch) -> None:
    """Negative control: gate 8 must still BLOCK a fresh BUY at saturation."""
    settings = _settings_with_env(monkeypatch)
    cap = settings.config.risk.max_total_exposure_usd
    portfolio = _saturated_portfolio("TSLAx", cap)

    result = evaluate_risk(
        ensemble=_ensemble(action="BUY", size_usd=25.0),
        features=_features(symbol="AAPLx"),
        portfolio=portfolio,
        settings=settings,
        is_exit_action=False,
    )

    assert result.approved is False
    assert any("exposure" in r for r in result.reasons), result.reasons
    cap_check = next(c for c in result.checks if c.name == "max_total_exposure")
    assert cap_check.passed is False


def test_sell_exit_cannot_open_short_via_execution_layer(monkeypatch) -> None:
    """End-to-end no-short safety.

    Even when the risk gate's carve-out approves an exit-SELL on an
    empty portfolio (because gate 8 trusts the caller about
    ``is_exit_action=True``), the downstream
    :func:`src.execution._execute_futures` layer refuses to open a
    short and returns a ``blocked`` ExecutionResult.
    """
    settings = _settings_with_env(monkeypatch)
    empty = PortfolioSnapshot(equity_usd=10_000.0, cash_usd=10_000.0, positions=[])
    ensemble = _ensemble(action="SELL", size_usd=25.0)

    risk_result = evaluate_risk(
        ensemble=ensemble,
        features=_features(symbol="AAPLx"),
        portfolio=empty,
        settings=settings,
        is_exit_action=True,
    )

    assert risk_result.approved is True, risk_result.reasons
    assert risk_result.adjusted_size_usd >= 0.0  # never negative

    blocked = execution_mod._execute_futures(
        mode="dry_run",
        features=_features(symbol="AAPLx", mark_price=100.0),
        ensemble=ensemble,
        size_usd=25.0,
        open_long_qty=0.0,
    )

    assert blocked.status == "blocked"
    assert blocked.error is not None
    assert "no open long" in blocked.error.lower() or "refuses to open shorts" in blocked.error.lower()
