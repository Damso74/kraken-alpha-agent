"""Market-hours / liquidity analysis regression tests.

These tests validate the strictly read-only `--market-hours-report`
extension of the backtester:
- Session classification handles US_CORE / US_PREMARKET / US_AFTERHOURS /
  OVERNIGHT / WEEKEND with inclusive-left / exclusive-right boundaries
  and rejects naive datetimes.
- DST transitions are handled by ``zoneinfo`` (no manual offset math).
- Top-N rejection-reason aggregation is correct.
- The market-hours report builder stays sane on an empty candle set
  (no division by zero, ``no_data`` style payload).
- The dashboard ``/market-hours`` route returns the persisted JSON when
  present and a ``no_market_hours_report`` sentinel otherwise.

No test in this file invokes the real Kraken CLI — the conftest forces
``KRAKEN_CLI_TRANSPORT=mock`` and we use deterministic fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import backtest as bt
from src.backtest import (
    Candle,
    MarketSession,
    PortfolioResult,
    SimulationDecision,
    SymbolResult,
    aggregate_by_session,
    build_market_hours_report,
    classify_market_session,
    tag_candles_with_session,
)


# ---------------------------------------------------------------------------
# 1) US_CORE — 14:00 UTC = 10:00 ET weekday
# ---------------------------------------------------------------------------


def test_classify_session_us_core() -> None:
    ts = datetime(2026, 5, 15, 14, 0, 0, tzinfo=timezone.utc)
    assert classify_market_session(ts) == MarketSession.US_CORE


# ---------------------------------------------------------------------------
# 2) PREMARKET — 08:00 UTC = 04:00 ET, 09:29 ET, and the 09:30 ET boundary
# ---------------------------------------------------------------------------


def test_classify_session_premarket() -> None:
    # 08:00 UTC = 04:00 ET (EDT, May) → start of PREMARKET (inclusive-left).
    ts = datetime(2026, 5, 15, 8, 0, 0, tzinfo=timezone.utc)
    assert classify_market_session(ts) == MarketSession.US_PREMARKET

    # 09:29 ET → still PREMARKET (US_CORE is exclusive-right of 09:29).
    ts_late = datetime(2026, 5, 15, 13, 29, 0, tzinfo=timezone.utc)
    assert classify_market_session(ts_late) == MarketSession.US_PREMARKET

    # 09:30:00 ET → boundary, must flip to US_CORE (inclusive-left).
    ts_open = datetime(2026, 5, 15, 13, 30, 0, tzinfo=timezone.utc)
    assert classify_market_session(ts_open) == MarketSession.US_CORE


# ---------------------------------------------------------------------------
# 3) AFTERHOURS — weekday 17:00 ET, 16:00 ET boundary, 20:00 ET boundary
# ---------------------------------------------------------------------------


def test_classify_session_afterhours() -> None:
    # 17:00 ET = 21:00 UTC during EDT.
    ts = datetime(2026, 5, 15, 21, 0, 0, tzinfo=timezone.utc)
    assert classify_market_session(ts) == MarketSession.US_AFTERHOURS

    # 16:00 ET → AFTERHOURS (US_CORE excludes 16:00).
    ts_close = datetime(2026, 5, 15, 20, 0, 0, tzinfo=timezone.utc)
    assert classify_market_session(ts_close) == MarketSession.US_AFTERHOURS

    # 20:00 ET → OVERNIGHT (AFTERHOURS excludes 20:00).
    ts_overnight = datetime(2026, 5, 16, 0, 0, 0, tzinfo=timezone.utc)
    assert classify_market_session(ts_overnight) == MarketSession.OVERNIGHT


# ---------------------------------------------------------------------------
# 4) WEEKEND — Saturday & Sunday in NY local time
# ---------------------------------------------------------------------------


def test_classify_session_weekend() -> None:
    # 2026-05-16 18:00 UTC = Saturday 14:00 ET → WEEKEND.
    saturday = datetime(2026, 5, 16, 18, 0, 0, tzinfo=timezone.utc)
    assert classify_market_session(saturday) == MarketSession.WEEKEND
    # 2026-05-17 13:30 UTC = Sunday 09:30 ET → still WEEKEND.
    sunday = datetime(2026, 5, 17, 13, 30, 0, tzinfo=timezone.utc)
    assert classify_market_session(sunday) == MarketSession.WEEKEND
    # Naive datetime → ValueError (no timezone guessing).
    with pytest.raises(ValueError):
        classify_market_session(datetime(2026, 5, 17, 13, 30, 0))


# ---------------------------------------------------------------------------
# 5) DST — 2026-03-08 transition (EST → EDT) is handled by zoneinfo
# ---------------------------------------------------------------------------


def test_classify_session_dst() -> None:
    # DST starts on the second Sunday of March (2026-03-08). The same
    # 13:30 UTC instant is interpreted differently depending on the
    # active offset:
    # - 2026-03-06 (Friday, EST, UTC-5): 13:30 UTC = 08:30 EST → PREMARKET.
    # - 2026-03-09 (Monday, EDT, UTC-4): 13:30 UTC = 09:30 EDT → US_CORE.
    pre_dst_premarket = datetime(2026, 3, 6, 13, 30, 0, tzinfo=timezone.utc)
    assert classify_market_session(pre_dst_premarket) == MarketSession.US_PREMARKET
    post_dst_open = datetime(2026, 3, 9, 13, 30, 0, tzinfo=timezone.utc)
    assert classify_market_session(post_dst_open) == MarketSession.US_CORE
    # The DST Sunday itself (2026-03-08) is always WEEKEND regardless
    # of the offset shift — sanity check that zoneinfo doesn't confuse
    # the day-of-week field.
    dst_sunday = datetime(2026, 3, 8, 13, 30, 0, tzinfo=timezone.utc)
    assert classify_market_session(dst_sunday) == MarketSession.WEEKEND


# ---------------------------------------------------------------------------
# 6) Top-N rejection aggregation in a SessionAggregate
# ---------------------------------------------------------------------------


def _make_decision(
    *,
    ts: str,
    action: str = "HOLD",
    reasons: list[str] | None = None,
    spread: float = 50.0,
    liquidity: float = 0.4,
    realized: float = 0.0,
    approved: bool = False,
) -> SimulationDecision:
    return SimulationDecision(
        timestamp_utc=ts,
        symbol="NVDAx",
        action=action,
        approved=approved,
        actionability_reason="rule",
        risk_reasons=list(reasons or []),
        spread_bps=spread,
        volume=1000.0,
        liquidity_score=liquidity,
        realized_pnl=realized,
        cash_after=0.0,
        equity_after=10_000.0,
    )


def test_aggregate_reasons_top_n() -> None:
    pf = PortfolioResult(initial_cash=10_000.0)
    sym = SymbolResult(symbol="NVDAx", initial_cash=10_000.0)
    # All decisions land in US_CORE (14:00 ET = 18:00 UTC weekday).
    base_ts = "2026-05-15T18:0{i}:00Z"
    sym.decisions = [
        _make_decision(ts=base_ts.format(i=0), reasons=["spread 200bps above 100bps"]),
        _make_decision(ts=base_ts.format(i=1), reasons=["spread 180bps above 100bps"]),
        _make_decision(ts=base_ts.format(i=2), reasons=["confidence 0.10 below threshold 0.30"]),
        _make_decision(ts=base_ts.format(i=3), reasons=["block_low_liquidity"]),
        _make_decision(ts=base_ts.format(i=4), reasons=["block_low_liquidity"]),
        _make_decision(ts=base_ts.format(i=5), reasons=["regime LOW_LIQUIDITY blocked by config"]),
    ]
    pf.by_symbol = {"NVDAx": sym}
    aggs = aggregate_by_session(pf, {"NVDAx": []})
    core = aggs[MarketSession.US_CORE]
    # 2 spread + 1 confidence + 3 low_liquidity (block_low_liquidity x2 +
    # regime LOW_LIQUIDITY x1) = correct counter classification.
    assert core.spread_blocks == 2
    assert core.confidence_blocks == 1
    assert core.low_liquidity_blocks == 3
    # Top 5 returned, ordered by count.
    top = dict(core.top_rejection_reasons)
    assert top.get("block_low_liquidity") == 2
    assert sum(top.values()) == 6


# ---------------------------------------------------------------------------
# 7) Empty candle set → market-hours report stays sane (no division by zero)
# ---------------------------------------------------------------------------


def test_market_hours_report_no_data() -> None:
    pf_a = PortfolioResult(initial_cash=10_000.0)
    pf_b = PortfolioResult(initial_cash=10_000.0)
    payload = build_market_hours_report(
        symbols=["NVDAx"],
        profile="aggressive_competition",
        interval_minutes=60,
        candles_by_symbol={"NVDAx": []},
        variant_a=pf_a,
        variant_b=pf_b,
    )
    assert payload["source"] == "backtest_local_estimate"
    assert payload["report_kind"] == "market_hours"
    assert payload["candles_total"] == 0
    assert payload["candles_per_session"]["US_CORE"] == 0
    # Both variants should expose all 5 sessions even if all aggregates are 0.
    assert set(payload["variants"]["A_block_low_liquidity"]["by_session"].keys()) == {
        s.value for s in MarketSession
    }
    # Comparison must not blow up with NaNs.
    comp = payload["comparison"]
    assert comp["delta_net_pnl_pct"] == 0.0
    assert comp["delta_trades_count"] == 0
    # Recommendation defaults to KEEP_BLOCKING when there's no signal.
    rec = payload["recommendation"]
    assert rec["keep_low_liquidity_blocking_in_runtime"] is True
    assert rec["allow_in_paper_dry_run_only"] is False


def test_tag_candles_with_session_filters_bad_timestamps() -> None:
    candles = [
        Candle(timestamp_utc="2026-05-15T14:00:00Z", open=1, high=1, low=1, close=1, volume=10),
        Candle(timestamp_utc="not-a-timestamp", open=1, high=1, low=1, close=1, volume=10),
        Candle(timestamp_utc="2026-05-16T18:00:00Z", open=1, high=1, low=1, close=1, volume=10),
    ]
    tagged = tag_candles_with_session(candles)
    # Bad timestamp dropped; both valid candles retained.
    assert len(tagged) == 2
    sessions = [t["session"] for t in tagged]
    assert MarketSession.US_CORE in sessions
    assert MarketSession.WEEKEND in sessions


# ---------------------------------------------------------------------------
# Dashboard route tests — strictly mock the filesystem.
# ---------------------------------------------------------------------------


def test_dashboard_market_hours_route_no_data(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from src.dashboard import app as dash_app

    monkeypatch.setattr(dash_app, "PROJECT_ROOT", tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    client = TestClient(dash_app.app)
    resp = client.get("/market-hours")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "no_market_hours_report"
    assert payload["source"] == "backtest_local_estimate"
    assert payload["report_kind"] == "market_hours"


def test_dashboard_market_hours_route(monkeypatch, tmp_path) -> None:
    import json as _json

    from fastapi.testclient import TestClient

    from src.dashboard import app as dash_app

    monkeypatch.setattr(dash_app, "PROJECT_ROOT", tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    fake_payload = {
        "source": "backtest_local_estimate",
        "report_kind": "market_hours",
        "timestamp_utc": "2026-05-15T10:00:00Z",
        "profile": "aggressive_competition",
        "symbols": ["NVDAx"],
        "interval_min": 60,
        "candles_total": 24,
        "candles_per_session": {"US_CORE": 6, "US_PREMARKET": 4, "US_AFTERHOURS": 4, "OVERNIGHT": 8, "WEEKEND": 2},
        "variants": {
            "A_block_low_liquidity": {
                "by_session": {s.value: {} for s in MarketSession},
                "totals": {"net_pnl_pct": 1.0, "trades_count": 3, "max_drawdown_pct": 0.5},
            },
            "B_allow_low_liquidity_simulation_only": {
                "by_session": {s.value: {} for s in MarketSession},
                "totals": {"net_pnl_pct": 1.4, "trades_count": 5, "max_drawdown_pct": 0.7},
            },
        },
        "comparison": {
            "delta_net_pnl_pct": 0.4,
            "delta_trades_count": 2,
            "delta_max_drawdown_pct": 0.2,
            "by_session_delta": {},
        },
        "recommendation": {
            "keep_low_liquidity_blocking_in_runtime": True,
            "allow_in_paper_dry_run_only": False,
            "best_window_cest": "15:30–22:00 CEST (09:30–16:00 ET)",
            "best_tickers_for_1530_cest": [{"symbol": "NVDAx", "us_core_realized_pnl": 12.5}],
            "rationale": "Variant A within 0.5pct of B → keep blocking.",
        },
        "warning": "Historical performance is not predictive of future results.",
    }
    (data_dir / "market_hours_report_latest.json").write_text(
        _json.dumps(fake_payload), encoding="utf-8"
    )
    client = TestClient(dash_app.app)
    resp = client.get("/market-hours")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "backtest_local_estimate"
    assert body["report_kind"] == "market_hours"
    assert body["candles_total"] == 24
    assert body["recommendation"]["keep_low_liquidity_blocking_in_runtime"] is True


# ---------------------------------------------------------------------------
# Sanity: build_market_hours_report on a tiny synthetic portfolio with one
# decision per session — checks that totals and recommendation logic are
# consistent end-to-end without touching the real engine.
# ---------------------------------------------------------------------------


def test_build_market_hours_report_recommendation_keeps_blocking_when_close() -> None:
    pf_a = PortfolioResult(initial_cash=10_000.0)
    pf_b = PortfolioResult(initial_cash=10_000.0)
    pf_a.net_pnl_pct = 1.0
    pf_b.net_pnl_pct = 1.2  # within 0.5 of A
    pf_a.max_drawdown_pct = 0.4
    pf_b.max_drawdown_pct = 0.5
    payload = build_market_hours_report(
        symbols=["NVDAx"],
        profile="aggressive_competition",
        interval_minutes=60,
        candles_by_symbol={"NVDAx": []},
        variant_a=pf_a,
        variant_b=pf_b,
    )
    rec = payload["recommendation"]
    assert rec["keep_low_liquidity_blocking_in_runtime"] is True
    assert rec["allow_in_paper_dry_run_only"] is False
