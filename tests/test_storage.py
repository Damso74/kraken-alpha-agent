from __future__ import annotations

import json
from pathlib import Path

from src.config import get_settings
from src.schemas import (
    Decision,
    ExecutionResult,
    Features,
    PnLSnapshot,
    PortfolioSnapshot,
    Position,
    RiskResult,
    StrategyVote,
)
from src.storage import (
    db_healthcheck,
    fetch_recent_decisions,
    fetch_recent_orders,
    fetch_recent_pnl,
    init_db,
    upsert_portfolio,
    write_decision,
    write_order,
    write_pnl,
)


def _decision() -> Decision:
    return Decision(
        symbol="NVDAx",
        action="BUY",
        final_score=0.4,
        confidence=0.6,
        suggested_size_usd=250.0,
        approved_size_usd=250.0,
        regime="TRENDING_UP",
        features=Features(
            symbol="NVDAx",
            last_price=900.0,
            bid=899.5,
            ask=900.5,
            spread_bps=5.5,
            return_5m=0.001,
            return_15m=0.003,
            return_1h=0.008,
            volatility_15m=0.002,
            volatility_1h=0.005,
            high_1h=905.0,
            low_1h=895.0,
            distance_from_high_1h=0.005,
            distance_from_low_1h=0.005,
            volume_1h=4000.0,
        ),
        votes=[StrategyVote(name="momentum", score=0.6, confidence=0.8)],
        risk=RiskResult(approved=True, adjusted_size_usd=250.0),
        execution=ExecutionResult(
            status="dry_run_logged",
            mode="dry_run",
            order_id="dry_test",
            symbol="NVDAx",
            action="BUY",
            requested_size_usd=250.0,
            fill_price=900.0,
            volume=0.27,
        ),
        mode="dry_run",
        rationale="test rationale",
    )


def test_init_db_creates_tables():
    init_db()
    health = db_healthcheck()
    assert health["ok"] is True
    for table in ("decisions", "orders", "positions", "pnl_snapshots", "errors", "cycles"):
        assert table in health["counts"]


def test_write_decision_persists_to_sqlite_and_jsonl():
    decision = _decision()
    write_decision(decision)

    rows = fetch_recent_decisions(limit=5)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NVDAx"
    payload = json.loads(rows[0]["payload_json"])
    assert payload["action"] == "BUY"

    jsonl_path = Path(get_settings().env.decisions_log_path)
    assert jsonl_path.exists()
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["symbol"] == "NVDAx"


def test_write_order_persists_to_sqlite_and_jsonl():
    decision = _decision()
    write_order(decision.id, decision.execution)
    rows = fetch_recent_orders(limit=5)
    assert len(rows) == 1
    assert rows[0]["status"] == "dry_run_logged"

    jsonl_path = Path(get_settings().env.trades_log_path)
    assert jsonl_path.exists()
    assert "dry_run_logged" in jsonl_path.read_text(encoding="utf-8")


def test_pnl_snapshot_round_trip():
    snap = PnLSnapshot(
        realized_usd=10.0,
        unrealized_usd=5.0,
        net_usd=15.0,
        equity_usd=10_015.0,
        drawdown_pct=0.0,
        note="unit test",
    )
    write_pnl(snap)
    rows = fetch_recent_pnl(limit=5)
    assert rows
    assert rows[0]["realized_usd"] == 10.0
    assert rows[0]["net_usd"] == 15.0


def test_upsert_portfolio_replaces_positions():
    snap = PortfolioSnapshot(
        cash_usd=5_000.0,
        equity_usd=10_000.0,
        positions=[
            Position(
                symbol="TSLAx",
                quantity=1.5,
                avg_entry_price=200.0,
                market_price=205.0,
                notional_usd=307.5,
                unrealized_pnl_usd=7.5,
                realized_pnl_usd=0.0,
            )
        ],
    )
    upsert_portfolio(snap)
    from src.storage import fetch_positions

    rows = fetch_positions()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "TSLAx"
    assert abs(rows[0]["notional_usd"] - 307.5) < 1e-6
