"""Regression tests for :mod:`src.research.paper_simulator`.

Pure-function tests only — no network, no filesystem, no subprocess.
"""

from __future__ import annotations

import math

import pytest

from src.research.paper_simulator import (
    DEFAULT_COST_MODEL,
    EligibilityInput,
    PaperCostModel,
    PaperTradeResult,
    check_paper_eligibility,
    compute_weekly_verdict,
    simulate_round_trip,
)


def test_round_trip_taker_default_is_one_percent() -> None:
    cost = DEFAULT_COST_MODEL.round_trip_cost_fraction(use_taker=True)
    assert math.isclose(cost, 0.01, rel_tol=0, abs_tol=1e-9)


def test_round_trip_fees_only_matches_g3_bar() -> None:
    fees = DEFAULT_COST_MODEL.round_trip_fees_only_fraction(use_taker=True)
    assert math.isclose(fees, 0.008, rel_tol=0, abs_tol=1e-9)


def test_simulate_round_trip_net_subtracts_cost() -> None:
    result = simulate_round_trip(0.02, use_taker=True)
    assert math.isclose(
        result.net_return,
        0.02 - DEFAULT_COST_MODEL.round_trip_cost_fraction(use_taker=True),
    )
    assert "COST_TAKER_ROUND_TRIP" in result.reason_codes


def test_simulate_round_trip_skip_when_edge_below_costs() -> None:
    result = simulate_round_trip(0.005, expected_edge_bps=50.0)
    assert "SKIP_EDGE_BELOW_COSTS" in result.reason_codes


def test_eligibility_pass_all_when_gates_satisfied() -> None:
    inp = EligibilityInput(
        n_events=20,
        bh_rejected=1,
        placebo_p_value=0.01,
        mean_return_post_7=0.015,
        jackknife_sign_preserved=True,
        jackknife_mean_drop_fraction=0.20,
        hit_rate_post_7=0.60,
        events_to_candles_ratio=0.10,
        oos_survives=True,
        max_event_pnl_share=0.30,
        n_regime_terciles_same_sign=2,
    )
    report = check_paper_eligibility(inp)
    assert report.eligible is True
    assert report.reason_codes == ("ELIG_PASS_ALL",)


def test_eligibility_fails_multiple_gates() -> None:
    inp = EligibilityInput(
        n_events=3,
        bh_rejected=0,
        placebo_p_value=0.20,
        mean_return_post_7=0.005,
        jackknife_sign_preserved=False,
        jackknife_mean_drop_fraction=0.60,
        hit_rate_post_7=0.40,
        events_to_candles_ratio=0.50,
        oos_survives=False,
        max_event_pnl_share=0.80,
        n_regime_terciles_same_sign=1,
    )
    report = check_paper_eligibility(inp)
    assert report.eligible is False
    assert "ELIG_G0_FAIL_EVENTS" in report.reason_codes
    assert "ELIG_G1_FAIL_BH" in report.reason_codes
    assert "ELIG_G3_FAIL_COST_DOMINANT" in report.reason_codes


def test_eligibility_exchange_status_requires_ten_events() -> None:
    inp = EligibilityInput(
        n_events=8,
        bh_rejected=1,
        placebo_p_value=0.01,
        mean_return_post_7=0.015,
        jackknife_sign_preserved=True,
        jackknife_mean_drop_fraction=0.10,
        hit_rate_post_7=0.55,
        events_to_candles_ratio=0.05,
        oos_survives=True,
        max_event_pnl_share=0.20,
        n_regime_terciles_same_sign=3,
        signal_id="exchange_status_major_incident",
    )
    report = check_paper_eligibility(inp)
    assert report.eligible is False
    assert "ELIG_G0_FAIL_EVENTS" in report.reason_codes


def test_weekly_verdict_insufficient_activity() -> None:
    trades = [simulate_round_trip(0.01)]
    verdict = compute_weekly_verdict(trades)
    assert verdict.verdict == "insufficient_activity"
    assert "WEEKLY_INSUFFICIENT_ACTIVITY" in verdict.reason_codes


def test_weekly_verdict_observe() -> None:
    trades = [
        simulate_round_trip(0.025),
        simulate_round_trip(0.020),
        simulate_round_trip(0.018),
    ]
    verdict = compute_weekly_verdict(trades)
    assert verdict.verdict == "observe"
    assert verdict.net_pnl_fraction > 0
    assert "WEEKLY_OBSERVE" in verdict.reason_codes


def test_weekly_verdict_degrade_on_negative_pnl() -> None:
    # Net PnL slightly negative, balanced trades, above -0.5 × costs.
    trades = [
        simulate_round_trip(0.0085),
        simulate_round_trip(0.0085),
    ]
    verdict = compute_weekly_verdict(trades)
    assert verdict.verdict == "degrade"
    assert "WEEKLY_DEGRADE" in verdict.reason_codes


def test_weekly_verdict_reject_on_concentration() -> None:
    big = simulate_round_trip(0.10)
    small = simulate_round_trip(0.001)
    verdict = compute_weekly_verdict([big, small])
    assert verdict.verdict == "reject"
    assert verdict.max_trade_concentration > 0.50


def test_weekly_verdict_deterministic() -> None:
    trades = [simulate_round_trip(0.02), simulate_round_trip(0.015)]
    a = compute_weekly_verdict(trades)
    b = compute_weekly_verdict(trades)
    assert a == b
