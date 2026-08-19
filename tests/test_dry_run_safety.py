"""Defense-in-depth tests for the dry_run mutation tripwire.

These tests guard the invariant that drives the 36-hour shadow xStocks
session: when ``mode == "dry_run"``, the execution layer **must** never
reach a wire-level mutating CLI call (`kraken_cli.place_order`,
`kraken_cli.validate_live_order`, `futures_kraken_cli.place_paper_order`,
`futures_kraken_cli.place_live_order`, `futures_kraken_cli.validate_via_paper`).

The tripwire itself lives in ``src/execution.py`` and raises
``DryRunMutationError`` when a future refactor lets a dry_run request
fall through to a mutating call.
"""

from __future__ import annotations

import pytest

from src import config as cfg
from src import futures_kraken_cli, kraken_cli
from src.execution import DryRunMutationError, _assert_not_dry_run, execute
from src.schemas import (
    EnsembleResult,
    Features,
    RiskCheck,
    RiskResult,
    StrategyVote,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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


def _risk_approved(size_usd: float = 25.0) -> RiskResult:
    return RiskResult(
        approved=True,
        reasons=[],
        checks=[RiskCheck(name="dummy", passed=True, detail="fixture")],
        adjusted_size_usd=size_usd,
        blocked_for_live_flags=False,
    )


# ---------------------------------------------------------------------------
# Tripwire helper unit tests
# ---------------------------------------------------------------------------


def test_assert_not_dry_run_raises_on_dry_run() -> None:
    with pytest.raises(DryRunMutationError) as excinfo:
        _assert_not_dry_run("dry_run", "kraken_cli.place_order(paper)")
    assert "dry_run safety violation" in str(excinfo.value)
    assert "kraken_cli.place_order(paper)" in str(excinfo.value)


def test_assert_not_dry_run_raises_case_insensitive() -> None:
    with pytest.raises(DryRunMutationError):
        _assert_not_dry_run("Dry_Run", "futures.place_paper_order")
    with pytest.raises(DryRunMutationError):
        _assert_not_dry_run("DRY_RUN", "futures.place_live_order")


def test_assert_not_dry_run_passthrough_for_paper_and_live() -> None:
    _assert_not_dry_run("paper", "kraken_cli.place_order(paper)")
    _assert_not_dry_run("live", "kraken_cli.place_order(live)")
    _assert_not_dry_run("PAPER", "futures.place_paper_order")
    _assert_not_dry_run("LIVE", "futures.place_live_order")


def test_dry_run_mutation_error_is_assertion_subclass() -> None:
    """The shadow session monitor watches for AssertionError; subclassing
    AssertionError makes both ``except AssertionError`` and
    ``except DryRunMutationError`` work without changing existing code.
    """
    assert issubclass(DryRunMutationError, AssertionError)


# ---------------------------------------------------------------------------
# Spot engine: dry_run never reaches kraken_cli.place_order
# ---------------------------------------------------------------------------


def test_spot_dry_run_never_calls_kraken_cli_place_order(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "dry_run")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "false")
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "aggressive_competition")
    cfg.get_settings.cache_clear()

    def fail_place(*a, **kw):
        pytest.fail("dry_run must never call kraken_cli.place_order")

    def fail_validate(*a, **kw):
        pytest.fail("dry_run must never call kraken_cli.validate_live_order")

    monkeypatch.setattr(kraken_cli, "place_order", fail_place)
    monkeypatch.setattr(kraken_cli, "validate_live_order", fail_validate)
    monkeypatch.setattr(kraken_cli, "paper_place_order", fail_place)

    result = execute(
        features=_features("NVDAx", price=940.0),
        ensemble=_ensemble("BUY", size_usd=25.0),
        risk=_risk_approved(25.0),
    )
    assert result.status == "dry_run_logged"
    assert result.mode == "dry_run"
    assert result.symbol == "NVDAx"

    cfg.get_settings.cache_clear()


def test_spot_dry_run_sell_also_skips_cli(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "dry_run")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "false")
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "aggressive_competition")
    cfg.get_settings.cache_clear()

    def fail_place(*a, **kw):
        pytest.fail("dry_run SELL must never reach kraken_cli.place_order")

    monkeypatch.setattr(kraken_cli, "place_order", fail_place)
    monkeypatch.setattr(kraken_cli, "validate_live_order", fail_place)

    result = execute(
        features=_features("AAPLx", price=220.0),
        ensemble=_ensemble("SELL", size_usd=20.0),
        risk=_risk_approved(20.0),
    )
    assert result.status == "dry_run_logged"
    assert result.action == "SELL"

    cfg.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Futures engine: dry_run never reaches futures_kraken_cli mutating calls
# ---------------------------------------------------------------------------


def test_futures_dry_run_never_calls_mutating_futures_cli(monkeypatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "dry_run")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "false")
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    cfg.get_settings.cache_clear()

    def fail(*a, **kw):
        pytest.fail("dry_run must never call any futures mutating wrapper")

    monkeypatch.setattr(futures_kraken_cli, "place_paper_order", fail)
    monkeypatch.setattr(futures_kraken_cli, "place_live_order", fail)
    monkeypatch.setattr(futures_kraken_cli, "validate_via_paper", fail)

    result = execute(
        features=_features("AAPLx", price=200.0),
        ensemble=_ensemble("BUY", size_usd=10.0),
        risk=_risk_approved(10.0),
    )
    assert result.status == "dry_run_logged"
    assert result.raw["engine"] == "futures"
    assert result.raw["mode"] == "futures_perp_1x"

    cfg.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Tripwire activates if a buggy refactor flips mode to dry_run after dispatch
# ---------------------------------------------------------------------------


def test_tripwire_fires_when_dry_run_reaches_paper_branch(monkeypatch) -> None:
    """If a future code change accidentally lets ``execute()`` fall through
    to the paper branch with mode=='dry_run', the tripwire must abort the
    call before any wire-level CLI invocation.
    """

    def boom_if_called(*a, **kw):
        pytest.fail(
            "kraken_cli.place_order should never be reached: tripwire must fire first"
        )

    monkeypatch.setattr(kraken_cli, "place_order", boom_if_called)

    with pytest.raises(DryRunMutationError):
        # Direct invocation of the helper at the same call sites used in
        # execute(). Mode is forcibly set to "dry_run" to simulate the
        # buggy fall-through.
        _assert_not_dry_run("dry_run", "kraken_cli.place_order(paper)")


def test_paper_mode_does_not_trip_paper_branch_guard() -> None:
    """The same call site, this time in genuine paper mode, must NOT raise."""

    _assert_not_dry_run("paper", "kraken_cli.place_order(paper)")
    _assert_not_dry_run("live", "kraken_cli.validate_live_order")
    _assert_not_dry_run("paper", "futures_kraken_cli.place_paper_order")
