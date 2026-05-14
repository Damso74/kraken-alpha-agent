"""Tests for the pure ranking module — no network access required."""

from __future__ import annotations

from src.ranking import (
    RankedSymbol,
    apply_filters,
    compute_symbol_rank,
    select_top_n,
    sort_ranking,
)


def _candles(prices: list[float]) -> list[dict]:
    out: list[dict] = []
    for i, p in enumerate(prices):
        out.append(
            {
                "timestamp": i * 3600,
                "open": p,
                "high": p * 1.005,
                "low": p * 0.995,
                "close": p,
                "vwap": p,
                "volume": 1000.0,
            }
        )
    return out


def _ticker(bid: float, ask: float, volume: float = 1000.0) -> dict:
    return {"bid": bid, "ask": ask, "last": (bid + ask) / 2, "volume_24h": volume}


def _orderbook(bid: float, ask: float) -> dict:
    return {
        "data": {
            "bids": [[str(bid), "1.0"]],
            "asks": [[str(ask), "1.0"]],
        }
    }


def _trades(n: int) -> dict:
    return {"data": [{"price": "1", "volume": "1"} for _ in range(n)]}


def test_opportunity_increases_with_momentum() -> None:
    flat = compute_symbol_rank(
        "AAPLx",
        pair="AAPLx/USD",
        ticker=_ticker(100, 100.05, volume=4000),
        candles=_candles([100, 100, 100, 100, 100]),
        orderbook=_orderbook(100, 100.05),
        trades=_trades(40),
    )
    up = compute_symbol_rank(
        "AAPLx",
        pair="AAPLx/USD",
        ticker=_ticker(100, 100.05, volume=4000),
        candles=_candles([100, 100.5, 101, 101.5, 102]),
        orderbook=_orderbook(100, 100.05),
        trades=_trades(40),
    )
    assert up.momentum_score > flat.momentum_score
    assert up.opportunity_score > flat.opportunity_score


def test_liquidity_score_responds_to_volume_and_spread() -> None:
    high_liq = compute_symbol_rank(
        "TSLAx",
        pair="TSLAx/USD",
        ticker=_ticker(200, 200.10, volume=8000),
        candles=_candles([200, 201, 202, 203, 204]),
        orderbook=_orderbook(200, 200.10),
        trades=_trades(80),
    )
    low_liq = compute_symbol_rank(
        "TSLAx",
        pair="TSLAx/USD",
        ticker=_ticker(200, 202.0, volume=50),
        candles=_candles([200, 201, 202, 203, 204]),
        orderbook=_orderbook(200, 202.0),
        trades=_trades(3),
    )
    assert high_liq.liquidity_score > low_liq.liquidity_score
    assert high_liq.spread_bps < low_liq.spread_bps


def test_apply_filters_excludes_wide_spread_and_low_volume() -> None:
    ok = compute_symbol_rank(
        "NVDAx",
        pair="NVDAx/USD",
        ticker=_ticker(50, 50.02, volume=4000),
        candles=_candles([50, 51, 52]),
        orderbook=_orderbook(50, 50.02),
        trades=_trades(40),
    )
    wide_spread = compute_symbol_rank(
        "MSTRx",
        pair="MSTRx/USD",
        ticker=_ticker(20, 22.0, volume=4000),  # ~1000 bps
        candles=_candles([20, 21, 22]),
        orderbook=_orderbook(20, 22.0),
        trades=_trades(40),
    )
    low_vol = compute_symbol_rank(
        "HOODx",
        pair="HOODx/USD",
        ticker=_ticker(10, 10.005, volume=10),
        candles=_candles([10, 11, 12]),
        orderbook=_orderbook(10, 10.005),
        trades=_trades(40),
    )
    annotated = apply_filters(
        [ok, wide_spread, low_vol],
        max_spread_bps=80,
        min_volume=100,
        min_trade_count=10,
    )
    by_sym = {r.symbol: r for r in annotated}
    assert by_sym["NVDAx"].skipped_reason is None
    assert "spread" in (by_sym["MSTRx"].skipped_reason or "")
    assert "volume" in (by_sym["HOODx"].skipped_reason or "")


def test_select_top_n_respects_size_and_only_picks_eligible() -> None:
    rows = []
    for i, sym in enumerate(["AAPLx", "TSLAx", "NVDAx", "MSTRx"]):
        r = compute_symbol_rank(
            sym,
            pair=f"{sym}/USD",
            ticker=_ticker(100 + i, 100 + i + 0.05, volume=4000),
            candles=_candles([100 + i, 101 + i, 102 + i, 103 + i, 104 + i]),
            orderbook=_orderbook(100 + i, 100 + i + 0.05),
            trades=_trades(40),
        )
        rows.append(r)
    # Mark one as skipped manually to ensure select_top_n ignores it.
    rows[1].skipped_reason = "manual skip"
    top = select_top_n(rows, top_n=2)
    assert len(top) == 2
    assert all(t.skipped_reason is None for t in top)
    # sort_ranking should sort by absolute opportunity_score
    sorted_rows = sort_ranking(rows)
    for i in range(len(sorted_rows) - 1):
        assert abs(sorted_rows[i].opportunity_score) >= abs(sorted_rows[i + 1].opportunity_score)


def test_compute_handles_missing_data_gracefully() -> None:
    r = compute_symbol_rank(
        "AAPLx",
        pair="AAPLx/USD",
        ticker=None,
        candles=None,
        orderbook=None,
        trades=None,
    )
    assert isinstance(r, RankedSymbol)
    assert r.last_price == 0.0
    assert r.spread_bps == 0.0
    assert r.trade_count_recent == 0
