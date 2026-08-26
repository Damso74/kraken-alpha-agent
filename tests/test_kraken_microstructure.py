from __future__ import annotations

from src.research.kraken_microstructure import (
    HOUR_SECONDS,
    MarketBar,
    RollingValues,
    TradeOutcome,
    analyze_segment,
    build_feature_points,
    build_trade_outcomes,
    generate_signal_events,
)


def test_rolling_values_use_nearest_rank() -> None:
    window = RollingValues()
    for index, value in enumerate(range(1, 11)):
        window.add(index, float(value))
    assert window.quantile(0.10) == 1.0
    assert window.quantile(0.90) == 9.0
    window.evict_before(5)
    assert len(window) == 5
    assert window.quantile(0.10) == 6.0


def _bar(timestamp: int, value: float = 100.0) -> MarketBar:
    return MarketBar(
        timestamp=timestamp,
        open=value,
        close=value,
        open_interest_close=1000.0,
        liquidation_volume=1.0,
        aggressor_differential=0.0,
    )


def test_feature_builder_refuses_hourly_gap() -> None:
    start = 1_700_000_000 - (1_700_000_000 % HOUR_SECONDS)
    bars = [_bar(start + index * HOUR_SECONDS) for index in range(30)]
    complete = build_feature_points(bars)
    assert complete

    with_gap = [bar for index, bar in enumerate(bars) if index != 10]
    after_gap = build_feature_points(with_gap)
    assert len(after_gap) < len(complete)


def test_events_are_causal_and_require_two_microstructure_conditions() -> None:
    from src.research.kraken_microstructure import FeaturePoint

    start = 1_600_000_000 - (1_600_000_000 % HOUR_SECONDS)
    points = [
        FeaturePoint(
            timestamp=start + index * HOUR_SECONDS,
            price_return_6h=0.001 * ((index % 11) - 5),
            oi_change_6h=0.001 * ((index % 13) - 6),
            liquidation_6h=float(index % 17),
            sell_aggression_6h=float((index % 19) - 9),
            volatility_24h=0.01 + (index % 10) * 0.001,
        )
        for index in range(4400)
    ]
    event_time = start + 4400 * HOUR_SECONDS
    points.append(
        FeaturePoint(
            timestamp=event_time,
            price_return_6h=-0.50,
            oi_change_6h=-0.50,
            liquidation_6h=1000.0,
            sell_aggression_6h=0.0,
            volatility_24h=0.02,
        )
    )
    micro, _, _ = generate_signal_events(points)
    assert any(event.timestamp == event_time for event in micro)

    points.append(
        FeaturePoint(
            timestamp=event_time + HOUR_SECONDS,
            price_return_6h=1.0,
            oi_change_6h=1.0,
            liquidation_6h=0.0,
            sell_aggression_6h=-1000.0,
            volatility_24h=0.01,
        )
    )
    micro_after_future, _, _ = generate_signal_events(points)
    assert [event.timestamp for event in micro_after_future if event.timestamp <= event_time] == [
        event.timestamp for event in micro if event.timestamp <= event_time
    ]


def test_trade_execution_starts_next_hour_and_holds_twelve_hours() -> None:
    from src.research.kraken_microstructure import SignalEvent

    start = 1_700_000_000 - (1_700_000_000 % HOUR_SECONDS)
    bars = [_bar(start + index * HOUR_SECONDS, 100.0 + index) for index in range(20)]
    event = SignalEvent(start, 5, True, True, False)
    outcomes = build_trade_outcomes(
        [event],
        bars,
        segment_start=start,
        segment_end=start + 20 * HOUR_SECONDS,
    )
    assert len(outcomes) == 1
    assert outcomes[0].entry_timestamp == start + HOUR_SECONDS
    assert outcomes[0].exit_timestamp == start + 13 * HOUR_SECONDS


def test_analysis_passes_only_when_all_preregistered_gates_pass() -> None:
    segment_start = 1_735_689_600  # 2025-01-01 UTC
    segment_end = 1_767_225_600  # 2026-01-01 UTC
    micro: list[TradeOutcome] = []
    baseline: list[TradeOutcome] = []
    for index in range(40):
        ts = segment_start + index * 7 * 86400
        micro.append(
            TradeOutcome(
                event_timestamp=ts,
                entry_timestamp=ts + HOUR_SECONDS,
                exit_timestamp=ts + 13 * HOUR_SECONDS,
                volatility_decile=index % 10,
                entry_price=100.0,
                exit_price=101.0,
                gross_return=0.01,
            )
        )
    for index in range(120):
        ts = segment_start + index * 2 * 86400
        baseline.append(
            TradeOutcome(
                event_timestamp=ts,
                entry_timestamp=ts + HOUR_SECONDS,
                exit_timestamp=ts + 13 * HOUR_SECONDS,
                volatility_decile=index % 10,
                entry_price=100.0,
                exit_price=99.9,
                gross_return=-0.001,
            )
        )

    result = analyze_segment(
        micro,
        baseline,
        segment_start=segment_start,
        segment_end=segment_end,
        eligible_bar_count=8000,
        data_quality_passed=True,
    )
    assert result["status"] == "pass"
    assert all(result["gates"].values())

    underpowered = analyze_segment(
        micro[:10],
        baseline,
        segment_start=segment_start,
        segment_end=segment_end,
        eligible_bar_count=8000,
        data_quality_passed=True,
    )
    assert underpowered["status"] == "insufficient_power"
