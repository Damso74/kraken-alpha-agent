"""Tests for :mod:`src.signals.wiki_attention`."""

from __future__ import annotations

from src.signals.wiki_attention import (
    CRYPTO_ATTENTION_BASKET,
    PREREGISTERED_Z_THRESHOLDS,
    build_preregistered_basket_momentum_events,
    build_wiki_attention_contrarian_events,
    build_wiki_attention_momentum_events,
    build_wiki_basket_aggregate_rows,
    build_wiki_basket_momentum_events,
    group_rows_by_article,
)


def _row(ts: int, pageviews: float, article: str = "Bitcoin") -> dict:
    return {"timestamp": ts, "pageviews": pageviews, "article": article}


def test_momentum_empty_on_insufficient_data() -> None:
    rows = [_row(1_700_000_000 + i * 86_400, 1000.0) for i in range(5)]
    assert build_wiki_attention_momentum_events(rows, lookback=30) == []


def test_momentum_detects_pageview_spike() -> None:
    base_ts = 1_700_000_000
    baseline = [1000.0 + i * 5.0 for i in range(25)]
    spike = [50_000.0]
    rows = [
        _row(base_ts + i * 86_400, pv)
        for i, pv in enumerate(baseline + spike)
    ]
    events = build_wiki_attention_momentum_events(
        rows, z_threshold=2.0, lookback=20
    )
    assert len(events) == 1
    assert events[0] == rows[-1]["timestamp"]


def test_contrarian_detects_attention_vacuum() -> None:
    base_ts = 1_700_050_000
    baseline = [10_000.0 + i * 10.0 for i in range(25)]
    dip = [50.0]
    rows = [
        _row(base_ts + i * 86_400, pv)
        for i, pv in enumerate(baseline + dip)
    ]
    events = build_wiki_attention_contrarian_events(
        rows, z_threshold=2.0, lookback=20
    )
    assert len(events) == 1


def test_momentum_and_contrarian_are_disjoint_on_same_spike() -> None:
    base_ts = 1_700_100_000
    rows = [
        _row(base_ts + i * 86_400, 1000.0 + i * 5.0) for i in range(25)
    ] + [_row(base_ts + 25 * 86_400, 80_000.0)]
    momentum = build_wiki_attention_momentum_events(rows, lookback=20)
    contrarian = build_wiki_attention_contrarian_events(rows, lookback=20)
    assert momentum
    assert not contrarian


def test_basket_aggregate_sums_daily_pageviews() -> None:
    base_ts = 1_700_200_000
    rows_by_article = {
        "Bitcoin": [_row(base_ts, 100.0, "Bitcoin")],
        "Ethereum": [_row(base_ts, 50.0, "Ethereum")],
    }
    agg = build_wiki_basket_aggregate_rows(rows_by_article)
    assert len(agg) == 1
    assert agg[0]["pageviews"] == 150.0


def test_basket_per_page_and_aggregate_events() -> None:
    base_ts = 1_700_300_000
    baseline = [1000.0 + i * 2.0 for i in range(25)]
    spike = [40_000.0]
    rows_btc = [
        _row(base_ts + i * 86_400, pv, "Bitcoin")
        for i, pv in enumerate(baseline + spike)
    ]
    rows_eth = [
        _row(base_ts + i * 86_400, 500.0 + i, "Ethereum")
        for i in range(26)
    ]
    rows_by_article = {"Bitcoin": rows_btc, "Ethereum": rows_eth}
    basket = build_wiki_basket_momentum_events(
        rows_by_article,
        z_threshold=2.0,
        lookback=20,
        articles=("Bitcoin", "Ethereum"),
    )
    assert len(basket.per_page["Bitcoin"]) == 1
    assert len(basket.basket_aggregate) >= 1


def test_preregistered_thresholds_only() -> None:
    assert PREREGISTERED_Z_THRESHOLDS == (1.5, 2.0)
    base_ts = 1_700_400_000
    rows = [
        _row(base_ts + i * 86_400, 1000.0 + i * 3.0) for i in range(30)
    ] + [_row(base_ts + 30 * 86_400, 25_000.0)]
    grouped = group_rows_by_article(rows)
    by_z = build_preregistered_basket_momentum_events(
        grouped,
        lookback=20,
        articles=("Bitcoin",),
    )
    assert set(by_z.keys()) == {1.5, 2.0}
    assert len(by_z[1.5].per_page["Bitcoin"]) >= len(by_z[2.0].per_page["Bitcoin"])


def test_crypto_basket_has_eight_pages() -> None:
    assert len(CRYPTO_ATTENTION_BASKET) == 8
    assert "USD Coin" in CRYPTO_ATTENTION_BASKET
    assert "Cryptocurrency exchange" in CRYPTO_ATTENTION_BASKET
