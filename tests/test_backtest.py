"""Backtester regression tests.

Safety invariants under test:
- SELL signals with no open position never open a short.
- SELL is exit-only: it can only reduce or close an existing long.
- Realised PnL on a SELL is computed via FIFO lot consumption.
- HOLD reasons are aggregated and surfaced via the result's top-N counters.
- Grid search selects the combo with the best ``net_pnl_pct - 0.5 * mdd``.
- An empty OHLC payload yields a clean ``status='no_data'`` (no divide-by-zero).

No test in this file shells out to the real Kraken CLI; the conftest forces
``KRAKEN_CLI_TRANSPORT=mock`` and we inject deterministic OHLC fixtures.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence
from unittest.mock import patch

import pytest

from src import backtest as bt
from src.backtest import (
    Candle,
    GridConfigResult,
    PortfolioResult,
    SymbolResult,
    _adjusted_score,
    _expand_grid,
    _pick_cautious,
    build_replay_candles,
    parse_ohlc_rows,
    run_grid_search,
    simulate_portfolio,
    simulate_symbol,
)
from src.config import get_settings


# ---------------------------------------------------------------------------
# Helpers — deterministic candle fixtures
# ---------------------------------------------------------------------------


def _trending_up_candles(start: float = 100.0, count: int = 24) -> list[Candle]:
    """Monotonically rising candles so momentum/breakout fire BUY signals."""
    out: list[Candle] = []
    price = start
    for i in range(count):
        open_ = price
        close = price * (1.0 + 0.015 + 0.001 * (i % 3))
        high = close * 1.005
        low = open_ * 0.998
        out.append(
            Candle(
                timestamp_utc=f"2026-05-15T{(8 + i) % 24:02d}:00:00Z",
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=5_000.0 + 100.0 * i,
                vwap=(open_ + close) / 2,
                trade_count=50 + i,
            )
        )
        price = close
    return out


def _trending_down_candles(start: float = 100.0, count: int = 24) -> list[Candle]:
    """Monotonically falling candles so momentum signals SELL."""
    out: list[Candle] = []
    price = start
    for i in range(count):
        open_ = price
        close = price * (1.0 - 0.015 - 0.001 * (i % 3))
        high = open_ * 1.002
        low = close * 0.995
        out.append(
            Candle(
                timestamp_utc=f"2026-05-15T{(8 + i) % 24:02d}:00:00Z",
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=5_000.0 + 100.0 * i,
                vwap=(open_ + close) / 2,
                trade_count=50 + i,
            )
        )
        price = close
    return out


def _zigzag_candles(start: float = 100.0, count: int = 30) -> list[Candle]:
    """Two BUY-ready up legs followed by a steep SELL leg."""
    out: list[Candle] = []
    price = start
    half = count // 2
    for i in range(half):
        open_ = price
        close = price * (1.0 + 0.02)
        out.append(
            Candle(
                timestamp_utc=f"2026-05-15T{(8 + i) % 24:02d}:00:00Z",
                open=open_,
                high=close * 1.005,
                low=open_ * 0.998,
                close=close,
                volume=6_000.0,
            )
        )
        price = close
    for i in range(count - half):
        open_ = price
        close = price * (1.0 - 0.025)
        out.append(
            Candle(
                timestamp_utc=f"2026-05-16T{(8 + i) % 24:02d}:00:00Z",
                open=open_,
                high=open_ * 1.001,
                low=close * 0.995,
                close=close,
                volume=6_000.0,
            )
        )
        price = close
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parse_ohlc_rows_accepts_dict_and_list_forms() -> None:
    rows = [
        {
            "timestamp": "2026-05-15T08:00:00Z",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "vwap": 100.25,
            "volume": 1000.0,
        },
        [1_715_760_000, 100.5, 101.5, 100.0, 101.0, 100.7, 1500.0, 10],
    ]
    parsed = parse_ohlc_rows("NVDAx", rows)
    assert len(parsed) == 2
    assert parsed[0].close == 100.5
    assert parsed[1].close == 101.0
    assert parsed[1].trade_count == 10


def test_backtest_no_short(monkeypatch) -> None:
    """SELL without an open long must never open a short."""
    settings = get_settings()
    candles = _trending_down_candles()
    result = simulate_symbol(
        "TSLAx",
        candles,
        config=settings.config,
        profile=settings.active_profile,
        initial_cash=10_000.0,
        settings=settings,
        block_low_liquidity=False,
    )
    # FIFO ledger should never go short.
    assert result.open_quantity >= 0
    # No SELL fills allowed without prior BUY.
    assert result.sell_count == 0
    # The actionability layer should have rejected SELL attempts.
    reasons = " ".join(result.actionability_reasons.keys())
    assert (
        "sell_without_position_shorting_disabled" in reasons
        or "hold" in reasons
        or "below" in reasons
    )


def test_backtest_sell_exit_only(monkeypatch) -> None:
    """A SELL fill must only reduce/close an existing long, never short."""
    settings = get_settings()
    candles = _zigzag_candles(count=30)
    result = simulate_symbol(
        "TSLAx",
        candles,
        config=settings.config,
        profile=settings.active_profile,
        initial_cash=10_000.0,
        settings=settings,
        block_low_liquidity=False,
    )
    # The simulator must never report a negative open quantity even after a
    # series of SELLs.
    assert result.open_quantity >= -1e-9
    # If any SELL fired it should be preceded by at least one BUY.
    if result.sell_count > 0:
        assert result.buy_count >= 1


def test_backtest_fifo_pnl(monkeypatch) -> None:
    """Two BUYs followed by one SELL → realised PnL is FIFO-correct."""
    state = bt._SimState(cash=10_000.0, peak_equity=10_000.0)
    # Lot 1: 10 @ 100; Lot 2: 5 @ 120.
    state.buy(qty=10.0, price=100.0)
    state.buy(qty=5.0, price=120.0)
    # SELL 12 @ 150 → 10 from lot1 + 2 from lot2.
    filled, pnl = state.sell_fifo(qty=12.0, price=150.0)
    assert filled == pytest.approx(12.0)
    # 10*(150-100) + 2*(150-120) = 500 + 60 = 560
    assert pnl == pytest.approx(560.0)
    assert state.quantity == pytest.approx(3.0)
    # Remaining lot: 3 @ 120 only.
    assert state.lots[0].price == pytest.approx(120.0)
    assert state.lots[0].qty == pytest.approx(3.0)


def test_backtest_hold_reasons(monkeypatch) -> None:
    """HOLD reasons must be aggregated and surfaced as a top-N counter."""
    settings = get_settings()
    flat: list[Candle] = []
    base = 100.0
    for i in range(20):
        flat.append(
            Candle(
                timestamp_utc=f"2026-05-15T{i:02d}:00:00Z",
                open=base,
                high=base * 1.0001,
                low=base * 0.9999,
                close=base,
                volume=10.0,  # very low liquidity → triggers gates
            )
        )
    result = simulate_symbol(
        "NVDAx",
        flat,
        config=settings.config,
        profile=settings.active_profile,
        initial_cash=10_000.0,
        settings=settings,
        block_low_liquidity=True,
    )
    assert result.hold_count > 0
    # At least one of the actionability reasons must appear in the counter.
    assert sum(result.actionability_reasons.values()) >= 1
    top = result.actionability_reasons.most_common(3)
    assert top[0][1] > 0


def test_grid_search_selects_best_adjusted_score() -> None:
    """The grid selector must rank by ``net_pnl_pct - 0.5 * mdd``."""
    def _pf(net: float, mdd: float, trades: int = 1) -> PortfolioResult:
        pf = PortfolioResult(initial_cash=10_000.0)
        pf.net_pnl_pct = net
        pf.max_drawdown_pct = mdd
        pf.trades_count = trades
        return pf

    combos = [
        GridConfigResult(overrides={"k": "a"}, portfolio=_pf(2.0, 8.0), adjusted_score=_adjusted_score(_pf(2.0, 8.0))),
        GridConfigResult(overrides={"k": "b"}, portfolio=_pf(5.0, 1.0), adjusted_score=_adjusted_score(_pf(5.0, 1.0))),
        GridConfigResult(overrides={"k": "c"}, portfolio=_pf(3.5, 4.0), adjusted_score=_adjusted_score(_pf(3.5, 4.0))),
    ]
    combos.sort(key=lambda c: c.adjusted_score, reverse=True)
    assert combos[0].overrides == {"k": "b"}
    # adjusted_score formula: 5.0 - 0.5 * 1.0 = 4.5 (vs 2.0 - 4.0 = -2.0)
    assert combos[0].adjusted_score == pytest.approx(4.5)


def test_grid_search_end_to_end_runs_and_returns_recommendation() -> None:
    """A tiny grid sweep on synthetic candles must terminate and return picks."""
    settings = get_settings()
    candles_up = [c for c in _trending_up_candles(count=20)]
    raw = [c.to_dict() for c in candles_up]
    grid = {
        "min_opportunity_score_buy": [0.02, 0.18],
        "min_opportunity_score_sell": [0.10],
        "max_spread_bps": [100],
        "top_n": [1],
        "block_low_liquidity": [True, False],
    }
    result = run_grid_search(
        ["NVDAx"],
        {"NVDAx": raw},
        config=settings.config,
        profile=settings.active_profile,
        grid=grid,
        initial_cash=10_000.0,
        settings=settings,
    )
    assert result.combos_evaluated == 2 * 1 * 1 * 1 * 2
    assert result.top_by_adjusted_score
    assert result.best_by_adjusted_score is not None
    # Cautious recommendation may be None if no combo traded, but the type
    # must be either dict or None — never raise.
    assert result.cautious_recommendation is None or isinstance(result.cautious_recommendation, dict)


def test_backtest_report_no_data() -> None:
    """Empty OHLC must produce a clean ``no_data`` status without crashing."""
    settings = get_settings()
    result = simulate_symbol(
        "NVDAx",
        [],
        config=settings.config,
        profile=settings.active_profile,
        initial_cash=10_000.0,
        settings=settings,
    )
    assert result.status == "no_data"
    assert result.trades_count == 0
    assert result.net_pnl == 0.0
    assert result.net_pnl_pct == 0.0
    # Portfolio aggregator must also stay clean.
    pf = simulate_portfolio(
        ["NVDAx"],
        {"NVDAx": []},
        config=settings.config,
        profile=settings.active_profile,
        initial_cash=10_000.0,
        settings=settings,
    )
    assert pf.trades_count == 0
    assert pf.net_pnl_pct == 0.0
    assert pf.equity_final == pf.initial_cash


def test_expand_grid_cartesian_product() -> None:
    grid = {"a": [1, 2], "b": ["x", "y", "z"]}
    combos = _expand_grid(grid)
    assert len(combos) == 6
    assert {"a": 1, "b": "x"} in combos
    assert {"a": 2, "b": "z"} in combos


def test_pick_cautious_prefers_low_drawdown() -> None:
    def _pf(net: float, mdd: float, trades: int = 5) -> PortfolioResult:
        pf = PortfolioResult(initial_cash=10_000.0)
        pf.net_pnl_pct = net
        pf.max_drawdown_pct = mdd
        pf.trades_count = trades
        return pf

    head = [
        GridConfigResult(overrides={"x": "low_dd"}, portfolio=_pf(4.0, 1.0), adjusted_score=3.5),
        GridConfigResult(overrides={"x": "high_dd"}, portfolio=_pf(8.0, 12.0), adjusted_score=2.0),
    ]
    cautious = _pick_cautious(head)
    assert cautious is not None
    # The cautious pick must be the lower-drawdown one even though the other
    # has a higher net_pnl_pct.
    assert cautious["overrides"] == {"x": "low_dd"}


def test_build_run_payload_carries_source_label() -> None:
    pf = PortfolioResult(initial_cash=1_000.0)
    payload = bt.build_run_payload(
        symbols=["NVDAx"],
        portfolio=pf,
        grid=None,
        profile="aggressive_competition",
        interval_minutes=60,
        candles_per_symbol={"NVDAx": 12},
    )
    assert payload["source"] == "backtest_local_estimate"
    assert payload["portfolio"]["source"] == "backtest_local_estimate"
    assert payload["candles_per_symbol"] == {"NVDAx": 12}


# ---------------------------------------------------------------------------
# Dashboard route tests — mock the filesystem, never touch the real CLI.
# ---------------------------------------------------------------------------


def test_dashboard_backtest_route_no_data(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from src.dashboard import app as dash_app

    # Force the dashboard to look for ``backtest_latest.json`` in an empty
    # tmp directory so the route returns the ``no_backtest`` sentinel.
    monkeypatch.setattr(dash_app, "PROJECT_ROOT", tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    client = TestClient(dash_app.app)
    resp = client.get("/backtest")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "no_backtest"
    assert payload["source"] == "backtest_local_estimate"


def test_dashboard_backtest_route(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from src.dashboard import app as dash_app

    monkeypatch.setattr(dash_app, "PROJECT_ROOT", tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    fake_payload = {
        "generated_at": "2026-05-15T10:00:00Z",
        "profile": "aggressive_competition",
        "symbols": ["NVDAx", "MSTRx"],
        "interval_minutes": 60,
        "source": "backtest_local_estimate",
        "portfolio": {
            "net_pnl_pct": 1.23,
            "trades_count": 4,
            "win_rate": 0.5,
            "max_drawdown_pct": 0.8,
            "buy_count": 2,
            "sell_count": 2,
            "hold_count": 10,
            "best_symbol": "NVDAx",
            "worst_symbol": "MSTRx",
            "source": "backtest_local_estimate",
        },
        "grid": {
            "best_by_adjusted_score": {
                "overrides": {"min_opportunity_score_buy": 0.06},
                "adjusted_score": 1.0,
            }
        },
    }
    import json as _json

    (data_dir / "backtest_latest.json").write_text(_json.dumps(fake_payload), encoding="utf-8")
    client = TestClient(dash_app.app)
    resp = client.get("/backtest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "backtest_local_estimate"
    assert body["portfolio"]["trades_count"] == 4
    assert body["symbols"] == ["NVDAx", "MSTRx"]
