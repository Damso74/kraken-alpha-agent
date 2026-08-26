from __future__ import annotations

import math
from unittest.mock import patch

from src.research.deribit_dvol import (
    DAY_SECONDS,
    ENTRY_DELAY_SECONDS,
    HOLD_SECONDS,
    DailyFeature,
    TradeOutcome,
    analyze_segment,
    build_daily_features,
    build_outcomes,
    quarterly_robustness,
)


def _daily_inputs(days: int = 440) -> tuple[list[dict], list[dict]]:
    start = 1_614_124_800  # 2021-02-24 00:00 UTC
    dvol: list[dict] = []
    prices: list[dict] = []
    for index in range(days):
        day = start + index * DAY_SECONDS
        close = 70.0 + 7.0 * math.sin(index / 9.0) + index * 0.01
        dvol.append({"timestamp": day, "close": close})
        prices.append(
            {"timestamp": day + 3_600, "open": 20_000.0 + index * 11.0}
        )
    return dvol, prices


def test_feature_history_is_causal() -> None:
    dvol, prices = _daily_inputs()
    features, diagnostics = build_daily_features(dvol, prices)
    assert features
    assert diagnostics["invalid_vov_windows"] == 0

    cutoff = features[-5].timestamp
    changed = [dict(row) for row in dvol]
    for row in changed:
        if row["timestamp"] > cutoff:
            row["close"] *= 3.0
    changed_features, _ = build_daily_features(changed, prices)
    before = [feature for feature in features if feature.timestamp <= cutoff]
    changed_before = [
        feature for feature in changed_features if feature.timestamp <= cutoff
    ]
    assert changed_before == before


def test_signal_execution_waits_until_next_day_and_avoids_overlap() -> None:
    start = 1_704_067_200  # 2024-01-01 UTC
    features = [
        DailyFeature(
            timestamp=start + index * DAY_SECONDS,
            vov7=2.0,
            q90=1.0,
            volatility_30d=0.02,
            volatility_decile=index % 10,
            is_signal=True,
        )
        for index in range(16)
    ]
    prices = []
    for index in range(25):
        timestamp = start + index * DAY_SECONDS + 3_600
        prices.append({"timestamp": timestamp, "open": 100.0 + index})
    signals, placebo, diagnostics = build_outcomes(
        features,
        prices,
        segment_start=start,
        segment_end=start + 16 * DAY_SECONDS,
    )
    assert not placebo
    assert len(signals) == 2
    assert signals[0].entry_timestamp == start + ENTRY_DELAY_SECONDS
    assert signals[0].exit_timestamp == signals[0].entry_timestamp + HOLD_SECONDS
    assert all(
        right.entry_timestamp >= left.exit_timestamp
        for left, right in zip(signals, signals[1:], strict=False)
    )
    assert diagnostics["skipped_signal_overlap"] == 6


def _outcome(timestamp: int, gross_return: float = 0.03) -> TradeOutcome:
    return TradeOutcome(
        event_timestamp=timestamp,
        entry_timestamp=timestamp + ENTRY_DELAY_SECONDS,
        exit_timestamp=timestamp + ENTRY_DELAY_SECONDS + HOLD_SECONDS,
        volatility_decile=timestamp % 10,
        entry_price=100.0,
        exit_price=100.0 * (1.0 + gross_return),
        gross_return=gross_return,
    )


def test_quarterly_robustness_requires_both_years() -> None:
    outcomes = []
    for year_start in (1_704_067_200, 1_735_689_600):
        outcomes.extend(
            _outcome(year_start + quarter * 91 * DAY_SECONDS)
            for quarter in range(4)
        )
    result = quarterly_robustness(outcomes, required_years=(2024, 2025))
    assert result["positive_each_year"] is True
    assert result["positive_leave_one_quarter_out"] is True
    assert result["acceptable_quarter_concentration"] is True


def test_analysis_requires_every_preregistered_gate() -> None:
    start = 1_704_067_200
    end = 1_767_225_600
    signals = [
        _outcome(start + index * 18 * DAY_SECONDS, 0.03) for index in range(40)
    ]
    placebo = [
        _outcome(start + index * 3 * DAY_SECONDS, -0.01) for index in range(200)
    ]
    with (
        patch(
            "src.research.deribit_dvol.block_bootstrap_lower_bound",
            return_value=0.01,
        ),
        patch(
            "src.research.deribit_dvol.matched_placebo_test",
            return_value={
                "replications": 2_000,
                "matched_mean": -0.01,
                "empirical_p_value": 0.001,
            },
        ),
    ):
        result = analyze_segment(
            signals,
            placebo,
            segment_start=start,
            segment_end=end,
            required_years=(2024, 2025),
            data_quality_passed=True,
        )
    assert result["status"] == "pass"
    assert all(result["gates"].values())

    with (
        patch(
            "src.research.deribit_dvol.block_bootstrap_lower_bound",
            return_value=0.01,
        ),
        patch(
            "src.research.deribit_dvol.matched_placebo_test",
            return_value={
                "replications": 2_000,
                "matched_mean": -0.01,
                "empirical_p_value": 0.001,
            },
        ),
    ):
        underpowered = analyze_segment(
            signals[:10],
            placebo,
            segment_start=start,
            segment_end=end,
            required_years=(2024, 2025),
            data_quality_passed=True,
        )
    assert underpowered["status"] == "insufficient_power"
