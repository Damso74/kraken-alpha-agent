from __future__ import annotations

from datetime import UTC, datetime

from src.research.quarter_hour import (
    DAY_SECONDS,
    ENTRY_OFFSET_MINUTES,
    EXIT_OFFSET_MINUTES,
    MINUTE_SECONDS,
    MinuteBar,
    TradeOutcome,
    analyze_segment,
    build_causal_weekly_thresholds,
    build_trade_outcomes,
    generate_events,
    nearest_rank,
    week_start_utc,
)


def test_generate_events_excludes_funding_settlement_hours() -> None:
    day = int(datetime(2025, 1, 2, tzinfo=UTC).timestamp())
    threshold_week = week_start_utc(day)
    bars = [
        MinuteBar(day + hour * 3600, 100.0, 100.0, 10.0)
        for hour in (0, 1, 8, 9, 16, 17)
    ]

    events = generate_events(
        bars,
        {threshold_week: 1.0},
        segment_start=day,
        segment_end=day + 86400,
        phase_minute=0,
    )

    assert [datetime.fromtimestamp(event.timestamp, tz=UTC).hour for event in events] == [
        1,
        9,
        17,
    ]


def _bar(timestamp: int, *, differential: float = 0.0, price: float = 100.0) -> MinuteBar:
    return MinuteBar(timestamp, price, price, differential)


def test_nearest_rank_and_week_start_are_deterministic() -> None:
    assert nearest_rank([1, 2, 3, 4, 5], 0.90) == 5.0
    timestamp = 1_735_689_600  # 2025-01-01 Wednesday UTC
    assert week_start_utc(timestamp) == 1_735_516_800  # Monday


def test_threshold_uses_only_minutes_strictly_before_week() -> None:
    week_start = 1_735_516_800
    start = week_start - 180 * DAY_SECONDS
    bars = [
        _bar(start + index * MINUTE_SECONDS, differential=float(index % 10))
        for index in range(180 * 24 * 60)
    ]
    thresholds, diagnostics = build_causal_weekly_thresholds(
        bars,
        segment_start=week_start,
        segment_end=week_start + 7 * DAY_SECONDS,
    )
    assert thresholds[week_start] == 8.0
    assert diagnostics["min_coverage"] == 1.0

    bars.append(_bar(week_start, differential=1_000_000.0))
    after_future, _ = build_causal_weekly_thresholds(
        bars,
        segment_start=week_start,
        segment_end=week_start + 7 * DAY_SECONDS,
    )
    assert after_future == thresholds


def test_event_phase_cooldown_and_execution_are_causal() -> None:
    week_start = 1_735_516_800
    event_base = week_start + 60 * MINUTE_SECONDS
    bars = [
        _bar(event_base + index * MINUTE_SECONDS, price=100.0 + index / 1000)
        for index in range(1_000)
    ]
    bars[0] = _bar(event_base, differential=10.0, price=100.0)
    bars[15] = _bar(event_base + 15 * MINUTE_SECONDS, differential=10.0, price=100.0)
    bars[480] = _bar(
        event_base + 480 * MINUTE_SECONDS, differential=10.0, price=101.0
    )
    events = generate_events(
        bars,
        {week_start: 1.0},
        segment_start=event_base,
        segment_end=event_base + 1_000 * MINUTE_SECONDS,
        phase_minute=0,
    )
    assert [event.timestamp for event in events] == [
        event_base,
        event_base + 480 * MINUTE_SECONDS,
    ]
    outcomes = build_trade_outcomes(
        events[:1],
        bars,
        segment_start=event_base,
        segment_end=event_base + 1_000 * MINUTE_SECONDS,
    )
    assert outcomes[0].entry_timestamp == event_base + ENTRY_OFFSET_MINUTES * 60
    assert outcomes[0].exit_timestamp == event_base + EXIT_OFFSET_MINUTES * 60


def _outcome(timestamp: int, gross_return: float) -> TradeOutcome:
    return TradeOutcome(
        event_timestamp=timestamp,
        entry_timestamp=timestamp + 60,
        exit_timestamp=timestamp + EXIT_OFFSET_MINUTES * 60,
        entry_price=100.0,
        exit_price=100.0 * (1.0 + gross_return),
        gross_return=gross_return,
    )


def test_analysis_needs_every_gate_and_family_adjusted_placebo() -> None:
    start = 1_735_689_600
    end = 1_767_225_600
    primary = [_outcome(start + index * DAY_SECONDS, 0.01) for index in range(320)]
    placebo = [_outcome(start + index * DAY_SECONDS, -0.001) for index in range(320)]
    result = analyze_segment(
        primary,
        placebo,
        segment_start=start,
        segment_end=end,
        data_quality_passed=True,
    )
    assert result["status"] == "pass"
    assert all(result["gates"].values())

    underpowered = analyze_segment(
        primary[:50],
        placebo,
        segment_start=start,
        segment_end=end,
        data_quality_passed=True,
    )
    assert underpowered["status"] == "insufficient_power"


def test_missing_history_refuses_threshold() -> None:
    week_start = 1_735_516_800
    bars = [
        _bar(week_start - 10 * DAY_SECONDS + index * MINUTE_SECONDS)
        for index in range(10 * 24 * 60)
    ]
    thresholds, diagnostics = build_causal_weekly_thresholds(
        bars,
        segment_start=week_start,
        segment_end=week_start + DAY_SECONDS,
    )
    assert thresholds == {}
    assert diagnostics["min_coverage"] < 0.95
