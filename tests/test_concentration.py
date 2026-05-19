"""Regression tests for :mod:`src.research.concentration`."""

from __future__ import annotations

import pytest

from src.research.concentration import (
    DEFAULT_MIN_EVENTS,
    MONTH_HIGH_RISK_SHARE,
    SINGLE_EVENT_HIGH_RISK_SHARE,
    TOP_N_DEFAULT,
    TOP_N_HIGH_RISK_SHARE,
    classify_concentration_risk,
    event_count_sufficiency,
    max_month_contribution,
    max_single_event_contribution,
    top_n_events_contribution,
)


def test_max_single_event_contribution_dominant_event() -> None:
    # 60 / 100 = 60 % > 20 %
    result = max_single_event_contribution([60.0, 10.0, 10.0, 10.0, 10.0])
    assert result.event_index == 0
    assert result.max_share == pytest.approx(0.6)
    assert result.high_risk is True


def test_max_single_event_contribution_balanced() -> None:
    # Six equal events → 1/6 ≈ 16.7 % each, below 20 %
    result = max_single_event_contribution([1.0] * 6)
    assert result.max_share == pytest.approx(1.0 / 6.0)
    assert result.high_risk is False


def test_max_single_event_contribution_at_threshold_not_high_risk() -> None:
    # Exactly 20 % is NOT > 20 %
    result = max_single_event_contribution([20.0, 20.0, 20.0, 20.0, 20.0])
    assert result.max_share == pytest.approx(0.2)
    assert result.high_risk is False


def test_max_single_event_contribution_just_above_threshold() -> None:
    result = max_single_event_contribution([21.0, 19.0, 20.0, 20.0, 20.0])
    assert result.max_share == pytest.approx(0.21)
    assert result.high_risk is True


def test_max_single_event_contribution_uses_absolute_values() -> None:
    # |-50| dominates despite negative sign
    result = max_single_event_contribution([-50.0, 10.0, 10.0, 10.0, 10.0])
    assert result.event_index == 0
    assert result.max_share == pytest.approx(50.0 / 90.0)
    assert result.high_risk is True


def test_max_single_event_contribution_all_zeros() -> None:
    result = max_single_event_contribution([0.0, 0.0, 0.0])
    assert result.max_share == 0.0
    assert result.high_risk is False
    assert result.total_abs == 0.0


def test_top_n_events_contribution_top_three_dominant() -> None:
    # top 3 abs: 40+30+25 = 95 / 100
    result = top_n_events_contribution([40.0, 30.0, 25.0, 3.0, 2.0], n=3)
    assert result.combined_share == pytest.approx(0.95)
    assert result.high_risk is True
    assert len(result.event_indices) == 3


def test_top_n_events_contribution_balanced_five_events() -> None:
    result = top_n_events_contribution([1.0, 1.0, 1.0, 1.0, 1.0], n=3)
    assert result.combined_share == pytest.approx(0.6)
    assert result.high_risk is True


def test_top_n_events_contribution_six_even_events_not_high_risk() -> None:
    result = top_n_events_contribution([1.0] * 6, n=3)
    assert result.combined_share == pytest.approx(0.5)
    assert result.high_risk is False


def test_top_n_events_contribution_at_threshold_not_high_risk() -> None:
    # top 3 of 6 equal → 3/6 = 50 % exactly
    result = top_n_events_contribution([1.0] * 6, n=3)
    assert result.combined_share == pytest.approx(0.5)
    assert result.high_risk is False


def test_max_month_contribution_from_months() -> None:
    contributions = [50.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    months = ["2024-01"] * 1 + ["2024-02"] * 5
    result = max_month_contribution(contributions, event_months=months)
    assert result.month == "2024-01"
    assert result.max_share == pytest.approx(50.0 / 100.0)
    assert result.high_risk is True


def test_max_month_contribution_from_timestamps() -> None:
    # 2024-06-01 UTC and 2024-07-01 UTC
    ts_june = 1_717_276_800
    ts_july = 1_719_955_200
    contributions = [45.0, 5.0, 5.0, 5.0]
    timestamps = [ts_june, ts_june, ts_july, ts_july]
    result = max_month_contribution(contributions, event_timestamps=timestamps)
    assert result.month == "2024-06"
    assert result.max_share == pytest.approx(50.0 / 60.0)
    assert result.high_risk is True


def test_max_month_contribution_balanced_months() -> None:
    contributions = [10.0, 10.0, 10.0, 10.0]
    months = ["2024-01", "2024-02", "2024-03", "2024-04"]
    result = max_month_contribution(contributions, event_months=months)
    assert result.max_share == pytest.approx(0.25)
    assert result.high_risk is False


def test_event_count_sufficiency_default_min_five() -> None:
    ok = event_count_sufficiency(5)
    low = event_count_sufficiency(4)
    assert ok.sufficient is True
    assert low.sufficient is False
    assert ok.min_events == DEFAULT_MIN_EVENTS


def test_classify_insufficient_evidence() -> None:
    result = classify_concentration_risk([1.0, 2.0, 3.0], event_months=["2024-01"] * 3)
    assert result.verdict == "insufficient_evidence"
    assert result.insufficient_evidence is True
    assert "event count 3" in result.reasons[0]


def test_classify_high_concentration_single_event() -> None:
    contributions = [80.0, 5.0, 5.0, 5.0, 5.0]
    months = ["2024-01"] * 5
    result = classify_concentration_risk(contributions, event_months=months)
    assert result.verdict == "high_concentration_risk"
    assert result.single_event_high_risk is True
    assert any("single event" in r for r in result.reasons)


def test_classify_acceptable() -> None:
    contributions = [2.0, 2.0, 2.0, 2.0, 2.0, 2.0]
    months = ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06"]
    result = classify_concentration_risk(contributions, event_months=months)
    assert result.verdict == "acceptable"
    assert result.reasons == ()


def test_classify_deterministic_repeat() -> None:
    contributions = [3.0, 3.0, 3.0, 3.0, 3.0]
    months = ["2024-07"] * 5
    a = classify_concentration_risk(contributions, event_months=months)
    b = classify_concentration_risk(contributions, event_months=months)
    assert a == b


def test_policy_constants_match_spec() -> None:
    assert SINGLE_EVENT_HIGH_RISK_SHARE == 0.20
    assert TOP_N_HIGH_RISK_SHARE == 0.50
    assert TOP_N_DEFAULT == 3
    assert MONTH_HIGH_RISK_SHARE == 0.40
    assert DEFAULT_MIN_EVENTS == 5


def test_max_single_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        max_single_event_contribution([])


def test_max_month_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length"):
        max_month_contribution([1.0, 2.0], event_months=["2024-01"])
