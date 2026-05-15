"""End-to-end futures-engine execution tests with mocked CLI.

Validates that:

* dry_run never shells out (no kraken subprocess invoked) but logs the
  futures payload with ``mode: "futures_perp_1x"`` and ``leverage=1.0``.
* Symbols without a futures listing (MSFTx, AMZNx, METAx) are blocked
  cleanly with a descriptive error.
* The validate-via-paper fallback is invoked before any live order when
  ``execution.require_validate_first`` is true.
* When validate-via-paper fails, the live branch refuses to send the
  real order.
* The order payload carries ``cli_ord_id``, ``mark_price``, the futures
  symbol, USD notional and ``mode: "futures_perp_1x"`` — the audit
  contract the rest of the agent relies on.
"""

from __future__ import annotations

import pytest

from src import config as cfg, futures_kraken_cli
from src.execution import _execute_futures
from src.futures_kraken_cli import to_futures_symbol
from src.schemas import EnsembleResult, Features, StrategyVote


def _features(symbol: str = "AAPLx", mark: float = 200.0, last: float = 200.0) -> Features:
    return Features(
        symbol=symbol,
        last_price=last,
        bid=last - 0.10, ask=last + 0.10, spread_bps=10.0,
        return_5m=0.001, return_15m=0.001, return_1h=0.001,
        volatility_15m=0.001, volatility_1h=0.001,
        high_1h=last * 1.01, low_1h=last * 0.99,
        distance_from_high_1h=0.01, distance_from_low_1h=0.01,
        volume_1h=5_000.0,
        mark_price=mark,
        funding_rate_pct_per_hour=0.0,
    )


def _ensemble(action: str = "BUY", size_usd: float = 10.0) -> EnsembleResult:
    return EnsembleResult(
        final_score=0.5, action=action,  # type: ignore[arg-type]
        confidence=0.7, suggested_size_usd=size_usd,
        votes=[StrategyVote(name="momentum", score=0.5, confidence=0.7)],
        regime="TRENDING_UP",
    )


@pytest.fixture()
def futures_profile(monkeypatch):
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    cfg.get_settings.cache_clear()
    yield cfg.get_settings()
    cfg.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Symbol mapping discovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spot,futures",
    [
        ("AAPLx", "PF_AAPLXUSD"),
        ("NVDAx/USD", "PF_NVDAXUSD"),
        ("TSLAx", "PF_TSLAXUSD"),
        ("GOOGLx", "PF_GOOGLXUSD"),
        ("SPYx", "PF_SPYXUSD"),
        ("QQQx", "PF_QQQXUSD"),
        ("MSTRx", "PF_MSTRXUSD"),
        ("CRCLx", "PF_CRCLXUSD"),
        ("HOODx", "PF_HOODXUSD"),
        ("GLDx", "PF_GLDXUSD"),
    ],
)
def test_symbol_mapping_matches_discovered_table(spot: str, futures: str) -> None:
    """The mapping table mirrors `kraken futures instruments` (2026-05-15)."""
    assert to_futures_symbol(spot) == futures


@pytest.mark.parametrize("missing", ["MSFTx", "AMZNx", "METAx", "BOGUSx"])
def test_symbol_without_futures_returns_none(missing: str) -> None:
    assert to_futures_symbol(missing) is None


def test_symbol_without_futures_blocks_order(futures_profile, monkeypatch) -> None:
    def fail(*a, **kw):
        pytest.fail(f"CLI must not be invoked when symbol has no futures listing, got {a} {kw}")

    monkeypatch.setattr(futures_kraken_cli, "place_paper_order", fail)
    monkeypatch.setattr(futures_kraken_cli, "place_live_order", fail)
    result = _execute_futures(
        mode="paper",
        features=_features(symbol="MSFTx"),
        ensemble=_ensemble("BUY"),
        size_usd=10.0,
        open_long_qty=0.0,
    )
    assert result.status == "blocked"
    assert "no futures listing" in (result.error or "")


# ---------------------------------------------------------------------------
# dry_run mode
# ---------------------------------------------------------------------------


def test_dry_run_does_not_shell_out_but_logs_futures_payload(
    futures_profile, monkeypatch
) -> None:
    def fail(*a, **kw):
        pytest.fail("dry_run must never invoke the futures CLI")

    monkeypatch.setattr(futures_kraken_cli, "place_paper_order", fail)
    monkeypatch.setattr(futures_kraken_cli, "place_live_order", fail)
    monkeypatch.setattr(futures_kraken_cli, "validate_via_paper", fail)

    result = _execute_futures(
        mode="dry_run",
        features=_features(),
        ensemble=_ensemble("BUY", size_usd=10.0),
        size_usd=10.0,
        open_long_qty=0.0,
    )
    assert result.status == "dry_run_logged"
    assert result.raw["engine"] == "futures"
    assert result.raw["mode"] == "futures_perp_1x"
    assert result.raw["leverage"] == 1.0
    assert result.raw["futures_symbol"] == "PF_AAPLXUSD"
    assert result.raw["notional_usd"] == pytest.approx(10.0)
    assert result.raw["mark_price"] == pytest.approx(200.0)
    assert result.raw["cli_ord_id"].startswith("fut")


# ---------------------------------------------------------------------------
# paper mode
# ---------------------------------------------------------------------------


def test_paper_buy_routes_through_futures_paper_cli(
    futures_profile, monkeypatch
) -> None:
    calls = {}

    def fake_paper(**kw):
        calls.update(kw)
        return futures_kraken_cli.FuturesCLIResult(
            ok=True, status="ok", transport="wsl",
            stdout_json={"order_id": "abc", "price": 200.0, "size": kw["size"], "cost": 10.0, "fee": 0.01},
        )

    monkeypatch.setattr(futures_kraken_cli, "place_paper_order", fake_paper)

    result = _execute_futures(
        mode="paper", features=_features(),
        ensemble=_ensemble("BUY"),
        size_usd=10.0, open_long_qty=0.0,
    )
    assert result.status == "futures_paper_filled"
    assert calls["leverage"] == 1.0
    assert calls["symbol"] == "PF_AAPLXUSD"
    assert calls["side"] == "BUY"
    assert calls["client_order_id"].startswith("fut")
    assert result.raw["mode"] == "futures_perp_1x"
    assert result.raw["cli_ord_id"] == calls["client_order_id"]


def test_paper_cli_failure_returns_futures_failed(
    futures_profile, monkeypatch
) -> None:
    def fail_paper(**kw):
        return futures_kraken_cli.FuturesCLIResult(
            ok=False, status="error", stderr="market closed",
            transport="wsl",
        )

    monkeypatch.setattr(futures_kraken_cli, "place_paper_order", fail_paper)

    result = _execute_futures(
        mode="paper", features=_features(),
        ensemble=_ensemble("BUY"),
        size_usd=10.0, open_long_qty=0.0,
    )
    assert result.status == "futures_failed"
    assert "market closed" in (result.error or "")


# ---------------------------------------------------------------------------
# live mode (triple opt-in needed)
# ---------------------------------------------------------------------------


def test_live_requires_triple_opt_in(futures_profile, monkeypatch) -> None:
    # Triple opt-in NOT set → live branch must refuse before any CLI call.
    def fail(*a, **kw):
        pytest.fail("live must not invoke any CLI when triple opt-in is off")

    monkeypatch.setattr(futures_kraken_cli, "place_paper_order", fail)
    monkeypatch.setattr(futures_kraken_cli, "place_live_order", fail)
    monkeypatch.setattr(futures_kraken_cli, "validate_via_paper", fail)
    result = _execute_futures(
        mode="live", features=_features(),
        ensemble=_ensemble("BUY"),
        size_usd=10.0, open_long_qty=0.0,
    )
    assert result.status == "blocked"
    assert "triple opt-in" in (result.error or "")


def test_live_runs_validate_before_real_order(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "true")
    cfg.get_settings.cache_clear()

    seen_order: dict = {"validate": False, "live": False}

    def fake_validate(**kw):
        seen_order["validate"] = True
        assert seen_order["live"] is False, "validate must run BEFORE live order"
        return futures_kraken_cli.FuturesCLIResult(
            ok=True, status="ok", transport="wsl",
            stdout_json={"order_id": "validate-paper-1", "price": 200.0, "size": kw["size"]},
        )

    def fake_live(**kw):
        seen_order["live"] = True
        assert seen_order["validate"] is True, "live must NOT run before validate"
        return futures_kraken_cli.FuturesCLIResult(
            ok=True, status="ok", transport="wsl",
            stdout_json={"order_id": "live-1", "price": 200.5, "size": kw["size"], "cost": 10.0, "fee": 0.01},
        )

    monkeypatch.setattr(futures_kraken_cli, "validate_via_paper", fake_validate)
    monkeypatch.setattr(futures_kraken_cli, "place_live_order", fake_live)

    result = _execute_futures(
        mode="live", features=_features(),
        ensemble=_ensemble("BUY"),
        size_usd=10.0, open_long_qty=0.0,
    )
    assert result.status == "futures_live_filled"
    assert seen_order["validate"] is True
    assert seen_order["live"] is True
    cfg.get_settings.cache_clear()


def test_live_aborts_when_validate_fails(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "true")
    cfg.get_settings.cache_clear()

    def fail_validate(**kw):
        return futures_kraken_cli.FuturesCLIResult(
            ok=False, status="error", stderr="symbol suspended", transport="wsl",
        )

    def fail_live(**kw):
        pytest.fail("live order must NOT be placed when validate fails")

    monkeypatch.setattr(futures_kraken_cli, "validate_via_paper", fail_validate)
    monkeypatch.setattr(futures_kraken_cli, "place_live_order", fail_live)

    result = _execute_futures(
        mode="live", features=_features(),
        ensemble=_ensemble("BUY"),
        size_usd=10.0, open_long_qty=0.0,
    )
    assert result.status == "futures_failed"
    assert "symbol suspended" in (result.error or "")
    cfg.get_settings.cache_clear()
