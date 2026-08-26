from __future__ import annotations

from dataclasses import replace

import pytest

from src.research.execution_toxicity import (
    CompletedProbe,
    ExecutionToxicityShadow,
    daily_block_bootstrap_lower_bound,
    summarize_shadow_observations,
)

BASE_MS = 1_700_000_000_000


def _book(timestamp_ms: int, *, bid: float = 100, ask: float = 101) -> dict:
    return {
        "event_type": "book_delta",
        "product_id": "PF_XBTUSD",
        "exchange_timestamp_ms": timestamp_ms,
        "received_wall_ns": (timestamp_ms + 10) * 1_000_000,
        "bid": bid,
        "bid_qty": 10,
        "ask": ask,
        "ask_qty": 10,
        "mid": (bid + ask) / 2,
        "imbalance": 0.0,
        "observed_transport_lag_ms": 10.0,
    }


def _trade(timestamp_ms: int, *, side: str, price: float, qty: float) -> dict:
    return {
        "event_type": "trade",
        "product_id": "PF_XBTUSD",
        "exchange_timestamp_ms": timestamp_ms,
        "received_wall_ns": (timestamp_ms + 10) * 1_000_000,
        "observed_transport_lag_ms": 10.0,
        "snapshot": False,
        "side": side,
        "price": price,
        "qty": qty,
    }


def test_toxic_sweep_routes_cross_and_records_three_markouts() -> None:
    engine = ExecutionToxicityShadow("PF_XBTUSD")
    engine.process_event(_book(BASE_MS))
    engine.process_event(_trade(BASE_MS + 1, side="buy", price=101, qty=10))
    assert engine.pending_count == 1
    engine.process_event(_book(BASE_MS + 5_001, bid=100.5, ask=101.5))
    engine.process_event(_book(BASE_MS + 30_001, bid=101, ask=102))
    completed = engine.process_event(_book(BASE_MS + 60_001, bid=102, ask=103))
    assert len(completed) == 1
    probe = completed[0]
    assert probe.route == "cross"
    assert probe.savings_bps == pytest.approx(0.0)
    assert probe.markout_5s_bps > 0
    assert probe.markout_30s_bps > probe.markout_5s_bps
    assert probe.markout_60s_bps > probe.markout_30s_bps


def test_passive_fill_requires_twice_displayed_queue() -> None:
    engine = ExecutionToxicityShadow("PF_XBTUSD")
    engine.process_event(_book(BASE_MS))
    # Opposite flow keeps aligned pressure low enough to select passive.
    engine.process_event(_trade(BASE_MS + 1, side="sell", price=100, qty=9))
    engine.process_event(_trade(BASE_MS + 2, side="buy", price=101, qty=10))
    engine.process_event(_trade(BASE_MS + 500, side="sell", price=100, qty=19))
    engine.process_event(_book(BASE_MS + 5_002))
    assert engine.pending_count == 1
    engine.process_event(_trade(BASE_MS + 600, side="sell", price=100, qty=1))
    engine.process_event(_book(BASE_MS + 30_002))
    completed = engine.process_event(_book(BASE_MS + 60_002))
    probe = completed[0]
    assert probe.route == "passive"
    assert probe.passive_filled is True
    assert probe.passive_traded_qty == pytest.approx(20)
    assert probe.completed_within_horizon is True
    assert probe.savings_bps > 0


def test_unfilled_passive_probe_is_forced_with_penalty() -> None:
    engine = ExecutionToxicityShadow("PF_XBTUSD")
    engine.process_event(_book(BASE_MS))
    engine.process_event(_trade(BASE_MS + 1, side="sell", price=100, qty=9))
    engine.process_event(_trade(BASE_MS + 2, side="buy", price=101, qty=10))
    engine.process_event(_book(BASE_MS + 60_002, bid=102, ask=103))
    probe = engine.completed[0]
    assert probe.route == "passive"
    assert probe.passive_filled is False
    assert probe.completed_within_horizon is False
    assert probe.router_implementation_shortfall_bps > probe.baseline_implementation_shortfall_bps
    assert probe.savings_bps < 0


def test_connection_reset_discards_pending_probe() -> None:
    engine = ExecutionToxicityShadow("PF_XBTUSD")
    engine.process_event(_book(BASE_MS))
    engine.process_event(_trade(BASE_MS + 1, side="buy", price=101, qty=10))
    assert engine.pending_count == 1
    engine.reset_connection()
    assert engine.pending_count == 0
    assert engine.discarded_pending_on_reset == 1


def test_trade_requires_strictly_earlier_and_fresh_book() -> None:
    equal_time = ExecutionToxicityShadow("PF_XBTUSD")
    equal_time.process_event(_book(BASE_MS))
    equal_time.process_event(_trade(BASE_MS, side="buy", price=101, qty=10))
    assert equal_time.pending_count == 0

    stale = ExecutionToxicityShadow("PF_XBTUSD")
    stale.process_event(_book(BASE_MS))
    stale.process_event(_trade(BASE_MS + 1_001, side="buy", price=101, qty=10))
    assert stale.pending_count == 0

    fresh = ExecutionToxicityShadow("PF_XBTUSD")
    fresh.process_event(_book(BASE_MS))
    fresh.process_event(_trade(BASE_MS + 1_000, side="buy", price=101, qty=10))
    assert fresh.pending_count == 1


def _completed(timestamp_ms: int, savings: float = 8.0) -> CompletedProbe:
    return CompletedProbe(
        probe_id=str(timestamp_ms),
        product_id="PF_XBTUSD",
        side="buy",
        route="passive",
        decision_timestamp_ms=timestamp_ms,
        completion_timestamp_ms=timestamp_ms + 60_000,
        decision_transport_lag_ms=10.0,
        sweep_ratio=1.0,
        aligned_pressure=0.0,
        aligned_imbalance=0.0,
        toxicity_score=1.0,
        queue_ahead_qty=10.0,
        passive_traded_qty=20.0,
        passive_filled=True,
        completed_within_horizon=True,
        baseline_implementation_shortfall_bps=20.0,
        router_implementation_shortfall_bps=12.0,
        savings_bps=savings,
        stress_savings_bps=savings - 5.0,
        markout_5s_bps=1.0,
        markout_30s_bps=2.0,
        markout_60s_bps=3.0,
    )


def test_daily_bootstrap_is_deterministic() -> None:
    observations = [_completed(BASE_MS + day * 86_400_000) for day in range(4)]
    first = daily_block_bootstrap_lower_bound(observations, replications=100, seed=7)
    second = daily_block_bootstrap_lower_bound(observations, replications=100, seed=7)
    assert first == second == pytest.approx(8.0)


def test_summary_fails_closed_when_power_is_insufficient() -> None:
    observations = [_completed(BASE_MS)]
    report = summarize_shadow_observations(observations)
    assert report["decision"] == "NO-GO"
    assert report["gates"]["passed"] is False
    assert "MIN_COMPLETED_PROBES" in report["gates"]["reason_codes"]
    assert report["safety"]["orders_sent"] == 0


def test_completion_gate_detects_forced_orders() -> None:
    observations = [_completed(BASE_MS + index) for index in range(20)]
    observations[0] = replace(observations[0], completed_within_horizon=False)
    observations[1] = replace(observations[1], completed_within_horizon=False)
    report = summarize_shadow_observations(observations)
    assert "COMPLETION_RATE_BELOW_95_PERCENT" in report["gates"]["reason_codes"]
