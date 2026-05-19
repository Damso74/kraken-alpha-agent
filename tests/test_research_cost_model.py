"""Tests for :mod:`src.research.cost_model` — deterministic, no network."""

from __future__ import annotations

import pytest

from src.research.cost_model import (
    MAKER_FEE_PCT,
    ROUND_TRIP_TAKER_TAKER_PCT,
    SUSPECT_GROSS_RETURN_THRESHOLD_PCT,
    TAKER_FEE_PCT,
    compute_net_event_return,
    estimate_round_trip_cost,
    summarize_cost_assumptions,
)


def test_fee_constants_match_kraken_conservative_defaults() -> None:
    assert MAKER_FEE_PCT == pytest.approx(0.0025)
    assert TAKER_FEE_PCT == pytest.approx(0.0040)
    assert ROUND_TRIP_TAKER_TAKER_PCT == pytest.approx(0.0080)
    assert SUSPECT_GROSS_RETURN_THRESHOLD_PCT == pytest.approx(0.0050)


def test_estimate_round_trip_taker_taker_major_pessimistic() -> None:
    cost = estimate_round_trip_cost(
        liquidity_tier="major",
        execution_style="taker_taker",
        pessimistic=True,
    )
    assert cost.fee_entry_pct == pytest.approx(TAKER_FEE_PCT)
    assert cost.fee_exit_pct == pytest.approx(TAKER_FEE_PCT)
    assert cost.spread_slippage_pct == pytest.approx(0.0020)
    assert cost.total_pct == pytest.approx(0.0080 + 0.0020)


def test_estimate_round_trip_alt_pessimistic_higher_than_major() -> None:
    major = estimate_round_trip_cost(liquidity_tier="major", pessimistic=True)
    alt = estimate_round_trip_cost(liquidity_tier="alt", pessimistic=True)
    assert alt.total_pct > major.total_pct


def test_estimate_round_trip_maker_maker_cheaper_than_taker_taker() -> None:
    taker = estimate_round_trip_cost(execution_style="taker_taker", pessimistic=True)
    maker = estimate_round_trip_cost(execution_style="maker_maker", pessimistic=True)
    assert maker.total_pct < taker.total_pct


def test_spread_override_is_deterministic() -> None:
    a = estimate_round_trip_cost(spread_slippage_pct=0.001)
    b = estimate_round_trip_cost(spread_slippage_pct=0.001)
    assert a == b
    assert a.spread_slippage_pct == pytest.approx(0.001)


def test_compute_net_event_return_with_dataclass() -> None:
    cost = estimate_round_trip_cost()
    gross = 0.015
    net = compute_net_event_return(gross, cost)
    assert net == pytest.approx(gross - cost.total_pct)


def test_compute_net_event_return_with_float() -> None:
    assert compute_net_event_return(0.01, 0.008) == pytest.approx(0.002)


def test_summarize_cost_assumptions_keys_and_flags() -> None:
    summary = summarize_cost_assumptions()
    assert summary["research_only"] is True
    assert summary["never_live_ready"] is True
    assert summary["fees"]["round_trip_taker_taker_pct"] == pytest.approx(0.0080)
    assert "example_round_trip_total_pct" in summary
    assert summary["example_round_trip_total_pct"]["alt_pessimistic"] > summary[
        "example_round_trip_total_pct"
    ]["major_pessimistic"]
