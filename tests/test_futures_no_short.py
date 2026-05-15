"""``execution._execute_futures`` no-short safeguard.

SELL is exit-only on the futures engine: it must reduce an existing long
and never open a new short. This file pins that contract by exercising
:func:`src.execution._execute_futures` directly with mocked CLI calls so
no real network/CLI interaction happens.
"""

from __future__ import annotations

import pytest

from src import config as cfg, execution as execution_mod, futures_kraken_cli
from src.execution import _execute_futures
from src.schemas import EnsembleResult, Features, StrategyVote


def _features() -> Features:
    return Features(
        symbol="AAPLx",
        last_price=200.0,
        bid=199.90, ask=200.10, spread_bps=10.0,
        return_5m=0.0, return_15m=0.0, return_1h=0.0,
        volatility_15m=0.0, volatility_1h=0.0,
        high_1h=202.0, low_1h=198.0,
        distance_from_high_1h=0.01, distance_from_low_1h=0.01,
        volume_1h=5_000.0,
        mark_price=200.0,
        funding_rate_pct_per_hour=0.0,
    )


def _ensemble(action: str) -> EnsembleResult:
    return EnsembleResult(
        final_score=0.5, action=action,  # type: ignore[arg-type]
        confidence=0.7, suggested_size_usd=10.0,
        votes=[StrategyVote(name="momentum", score=0.5, confidence=0.7)],
        regime="TRENDING_UP",
    )


@pytest.fixture()
def futures_profile(monkeypatch):
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    cfg.get_settings.cache_clear()
    yield cfg.get_settings()
    cfg.get_settings.cache_clear()


def test_sell_without_long_is_refused(futures_profile, monkeypatch) -> None:
    captured: list = []
    monkeypatch.setattr(
        futures_kraken_cli, "place_paper_order",
        lambda **kw: captured.append(("paper", kw)) or pytest.fail("must not be called"),
    )
    monkeypatch.setattr(
        futures_kraken_cli, "place_live_order",
        lambda **kw: captured.append(("live", kw)) or pytest.fail("must not be called"),
    )

    result = _execute_futures(
        mode="paper",
        features=_features(),
        ensemble=_ensemble("SELL"),
        size_usd=10.0,
        open_long_qty=0.0,
    )
    assert result.status == "blocked"
    assert "SELL without open long" in (result.error or "")
    assert captured == []


def test_sell_with_long_routes_reduce_only_paper(futures_profile, monkeypatch) -> None:
    payload = {"order_id": "paper-abc", "price": 200.0, "size": 0.04, "cost": 8.0}
    calls = {}

    def fake_paper(**kw):
        calls.update(kw)
        return futures_kraken_cli.FuturesCLIResult(
            ok=True, status="ok", stdout_json=payload, transport="wsl",
        )

    monkeypatch.setattr(futures_kraken_cli, "place_paper_order", fake_paper)

    result = _execute_futures(
        mode="paper",
        features=_features(),
        ensemble=_ensemble("SELL"),
        size_usd=10.0,
        open_long_qty=0.04,
    )
    assert result.status == "futures_paper_filled"
    assert calls["reduce_only"] is True
    assert calls["side"] == "SELL"
    assert calls["symbol"] == "PF_AAPLXUSD"
    assert calls["leverage"] == 1.0


def test_sell_size_clamped_to_open_long(futures_profile, monkeypatch) -> None:
    """Even when the strategy suggests a larger SELL, we clamp to the open qty
    so we never accidentally cross zero into a short."""
    calls = {}

    def fake_paper(**kw):
        calls.update(kw)
        return futures_kraken_cli.FuturesCLIResult(
            ok=True, status="ok",
            stdout_json={"order_id": "paper-x", "price": 200.0, "size": kw["size"]},
            transport="wsl",
        )

    monkeypatch.setattr(futures_kraken_cli, "place_paper_order", fake_paper)

    # The ensemble wants a 50 USD SELL = 0.25 contracts at $200, but we only
    # hold 0.02 contracts. The futures branch must clamp to 0.02.
    result = _execute_futures(
        mode="paper",
        features=_features(),
        ensemble=_ensemble("SELL"),
        size_usd=50.0,
        open_long_qty=0.02,
    )
    assert result.status == "futures_paper_filled"
    assert calls["size"] == pytest.approx(0.02, rel=1e-6)
    assert calls["reduce_only"] is True


def test_buy_does_not_set_reduce_only(futures_profile, monkeypatch) -> None:
    calls = {}

    def fake_paper(**kw):
        calls.update(kw)
        return futures_kraken_cli.FuturesCLIResult(
            ok=True, status="ok",
            stdout_json={"order_id": "paper-buy", "price": 200.0, "size": kw["size"]},
            transport="wsl",
        )

    monkeypatch.setattr(futures_kraken_cli, "place_paper_order", fake_paper)

    result = _execute_futures(
        mode="paper",
        features=_features(),
        ensemble=_ensemble("BUY"),
        size_usd=10.0,
        open_long_qty=0.0,
    )
    assert result.status == "futures_paper_filled"
    assert calls["reduce_only"] is False
    assert calls["side"] == "BUY"
