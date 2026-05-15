"""Tests for the paper-run analyser — covers parsing, FIFO PnL, and rendering."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.paper_run_analysis import compute_report, render_markdown


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _decision(at: datetime, *, symbol: str, action: str, score: float, reason: str = "buy_eligible") -> dict:
    return {
        "at": _iso(at),
        "symbol": symbol,
        "action": action,
        "final_score": score,
        "confidence": 0.5,
        "approved": 1,
        "payload_json": json.dumps({"actionability": {"reason": reason}, "risk": {"reasons": []}}),
    }


def _order(at: datetime, *, symbol: str, action: str, status: str, price: float, volume: float) -> dict:
    return {
        "at": _iso(at),
        "symbol": symbol,
        "action": action,
        "status": status,
        "payload_json": json.dumps({
            "status": status,
            "fill_price": price,
            "volume": volume,
            "fee": 0.0,
            "symbol": symbol,
            "action": action,
        }),
    }


def _pnl(at: datetime, *, realized: float, unrealized: float, equity: float) -> dict:
    net = realized + unrealized
    return {
        "at": _iso(at),
        "realized_usd": realized,
        "unrealized_usd": unrealized,
        "net_usd": net,
        "equity_usd": equity,
    }


def test_no_data_path_returns_friendly_message() -> None:
    report = compute_report(
        decisions=[], orders=[], pnl_snapshots=[], cycles=[], errors=[],
        since_hours=24.0, profile="balanced", generated_at=_iso(_now()),
    )
    assert report.no_data is True
    md = render_markdown(report)
    assert "No paper run data yet" in md


def test_basic_session_counts_actions_and_top_symbols() -> None:
    now = _now()
    decisions = [
        _decision(now - timedelta(minutes=5), symbol="AAPLx", action="BUY", score=0.4),
        _decision(now - timedelta(minutes=4), symbol="AAPLx", action="HOLD", score=0.05, reason="below_buy_threshold"),
        _decision(now - timedelta(minutes=3), symbol="TSLAx", action="HOLD", score=-0.1, reason="negative_opportunity"),
    ]
    orders = [
        _order(now - timedelta(minutes=5), symbol="AAPLx", action="BUY", status="paper_filled", price=100.0, volume=1.0),
        _order(now - timedelta(minutes=3), symbol="AAPLx", action="SELL", status="paper_filled", price=105.0, volume=1.0),
        _order(now - timedelta(minutes=2), symbol="MSTRx", action="BUY", status="blocked", price=0.0, volume=0.0),
    ]
    pnl = [_pnl(now - timedelta(minutes=1), realized=5.0, unrealized=0.0, equity=10_005.0)]
    report = compute_report(
        decisions=decisions, orders=orders, pnl_snapshots=pnl,
        cycles=[{"started_at": _iso(now - timedelta(minutes=6)), "duration_ms": 1500}],
        errors=[],
        since_hours=1.0, profile="balanced", generated_at=_iso(now),
    )
    assert report.no_data is False
    assert report.cycles_count == 1
    assert report.actions_distribution["BUY"] == 1
    assert report.actions_distribution["HOLD"] == 2
    assert report.actionability_reasons.get("below_buy_threshold") == 1
    assert report.actionability_reasons.get("negative_opportunity") == 1
    assert any(s["symbol"] == "AAPLx" for s in report.top_symbols)
    assert report.execution_statuses["paper_filled"] == 2
    assert report.execution_statuses["blocked"] == 1
    assert report.pnl_net_usd == 5.0


def test_fifo_pairs_buys_and_sells_and_computes_pnl() -> None:
    now = _now()
    orders = [
        _order(now - timedelta(minutes=10), symbol="AAPLx", action="BUY",
               status="paper_filled", price=100.0, volume=2.0),
        _order(now - timedelta(minutes=5), symbol="AAPLx", action="SELL",
               status="paper_filled", price=110.0, volume=1.0),
        _order(now - timedelta(minutes=4), symbol="AAPLx", action="SELL",
               status="paper_filled", price=90.0, volume=1.0),
    ]
    report = compute_report(
        decisions=[], orders=orders, pnl_snapshots=[], cycles=[], errors=[],
        since_hours=1.0, profile="balanced", generated_at=_iso(now),
    )
    assert len(report.fifo_trades) == 2
    pnls = sorted(t["pnl_usd"] for t in report.fifo_trades)
    # +10 (sold 1 @110 vs entry 100) and -10 (sold 1 @90 vs entry 100).
    assert pnls == [-10.0, 10.0]
    assert report.wins == 1
    assert report.losses == 1
    assert report.win_rate == 0.5


def test_render_markdown_contains_expected_sections() -> None:
    now = _now()
    report = compute_report(
        decisions=[_decision(now, symbol="AAPLx", action="BUY", score=0.3)],
        orders=[_order(now, symbol="AAPLx", action="BUY",
                       status="paper_filled", price=100.0, volume=1.0)],
        pnl_snapshots=[_pnl(now, realized=0.0, unrealized=2.5, equity=10_002.5)],
        cycles=[{"started_at": _iso(now), "duration_ms": 800}],
        errors=[],
        since_hours=24.0, profile="aggressive_competition", generated_at=_iso(now),
    )
    md = render_markdown(report)
    assert "Paper Run Report" in md
    assert "Executive summary" in md
    assert "Execution statuses" in md
    assert "Opportunity score distribution" in md
    assert "aggressive_competition" in md


def test_window_filter_drops_old_data() -> None:
    now = _now()
    old = now - timedelta(hours=48)
    decisions = [_decision(old, symbol="AAPLx", action="BUY", score=0.4)]
    report = compute_report(
        decisions=decisions, orders=[], pnl_snapshots=[], cycles=[], errors=[],
        since_hours=1.0, profile="balanced", generated_at=_iso(now),
    )
    assert report.no_data is True
