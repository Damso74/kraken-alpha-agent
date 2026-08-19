"""Tests for :mod:`src.research.tradeability` — deterministic, no network."""

from __future__ import annotations

from src.research.cost_model import (
    SUSPECT_GROSS_RETURN_THRESHOLD_PCT,
    RoundTripCost,
)
from src.research.tradeability import (
    TradeabilityVerdict,
    classify_tradeability,
    reject_if_cost_dominated,
)


def test_verdict_never_live_ready() -> None:
    for verdict in TradeabilityVerdict:
        assert verdict.is_live_ready is False


def test_classify_suspect_gross_below_threshold() -> None:
    assessment = classify_tradeability(0.003)
    assert assessment.verdict == TradeabilityVerdict.ECONOMICALLY_IMPOSSIBLE
    assert assessment.reject is True


def test_classify_cost_dominated_when_gross_below_round_trip() -> None:
    # Above suspect floor but below default major pessimistic total (~1.0 %)
    assessment = classify_tradeability(0.007)
    assert assessment.verdict == TradeabilityVerdict.COST_DOMINATED
    assert assessment.reject is True
    assert assessment.net_mean_return_pct <= 0.0


def test_classify_research_only_thin_net_edge() -> None:
    # Gross clears costs but net < 50 % of cost buffer
    cost_total = 0.010
    gross = cost_total + 0.002
    assessment = classify_tradeability(
        gross,
        round_trip_cost=RoundTripCost(
            fee_entry_pct=0.004,
            fee_exit_pct=0.004,
            spread_slippage_pct=0.002,
            total_pct=cost_total,
            liquidity_tier="major",
            execution_style="taker_taker",
            pessimistic=True,
        ),
    )
    assert assessment.verdict == TradeabilityVerdict.RESEARCH_ONLY
    assert assessment.reject is False


def test_classify_paper_candidate_requires_bh_and_oos() -> None:
    gross = 0.025
    assessment = classify_tradeability(
        gross,
        n_events=10,
        bh_supported=True,
        oos_confirmed=True,
    )
    assert assessment.verdict == TradeabilityVerdict.CANDIDATE_FOR_PAPER_OBSERVATION
    assert assessment.live_ready is False
    assert assessment.net_mean_return_pct > 0.0


def test_classify_low_event_count_caps_at_research_only() -> None:
    gross = 0.025
    assessment = classify_tradeability(
        gross,
        n_events=3,
        bh_supported=True,
        oos_confirmed=True,
    )
    assert assessment.verdict == TradeabilityVerdict.RESEARCH_ONLY
    assert "events" in assessment.reason.lower()


def test_reject_if_cost_dominated_matches_classify() -> None:
    gross = 0.003
    reject, reason, verdict = reject_if_cost_dominated(gross)
    assert reject is True
    assert verdict == TradeabilityVerdict.ECONOMICALLY_IMPOSSIBLE
    assert reason


def test_reject_if_cost_dominated_false_for_strong_net() -> None:
    gross = 0.030
    reject, _, verdict = reject_if_cost_dominated(gross)
    assert reject is False
    assert verdict in (
        TradeabilityVerdict.RESEARCH_ONLY,
        TradeabilityVerdict.CANDIDATE_FOR_PAPER_OBSERVATION,
    )


def test_suspect_threshold_boundary() -> None:
    at = classify_tradeability(SUSPECT_GROSS_RETURN_THRESHOLD_PCT)
    below = classify_tradeability(SUSPECT_GROSS_RETURN_THRESHOLD_PCT - 1e-9)
    assert below.verdict == TradeabilityVerdict.ECONOMICALLY_IMPOSSIBLE
    assert at.verdict != TradeabilityVerdict.ECONOMICALLY_IMPOSSIBLE or at.reject is False
