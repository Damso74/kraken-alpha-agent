from __future__ import annotations

from unittest.mock import patch

from src.research.cross_venue_order_flow import (
    DAY_SECONDS,
    HOUR_SECONDS,
    WEEK_SECONDS,
    TradeOutcome,
    analyze_segment,
    build_outcomes,
    build_weekly_features,
    stratified_permutation_test,
)


def _inputs(days: int = 900) -> tuple[list[dict], list[dict], list[dict]]:
    start = 1_646_006_400  # 2022-03-01 UTC
    binance: list[dict] = []
    kraken: list[dict] = []
    prices: list[dict] = []
    for index in range(days):
        timestamp = start + index * DAY_SECONDS
        quote = 1_000_000.0
        taker_buy = quote * (0.55 if (index // 7) % 2 == 0 else 0.45)
        binance.append(
            {
                "timestamp": timestamp,
                "quote_volume": quote,
                "taker_buy_quote_volume": taker_buy,
            }
        )
        buy = 550.0 if (index // 7) % 3 else 450.0
        sell = 1_000.0 - buy
        kraken.append(
            {"timestamp": timestamp, "buy_volume": buy, "sell_volume": sell}
        )
        prices.extend(
            [
                {"timestamp": timestamp, "open": 20_000.0 + index * 10.0},
                {
                    "timestamp": timestamp + HOUR_SECONDS,
                    "open": 20_001.0 + index * 10.0,
                },
            ]
        )
    return binance, kraken, prices


def test_weekly_features_use_complete_prior_weeks_and_causal_volatility() -> None:
    binance, kraken, prices = _inputs()
    features, diagnostics = build_weekly_features(binance, kraken, prices)
    assert features
    assert diagnostics["common_days"] == 900
    assert diagnostics["eligible_weeks"] == len(features)
    assert features[0].decision_timestamp - features[0].source_week_start == WEEK_SECONDS
    assert all(0 <= feature.volatility_decile <= 9 for feature in features)

    cutoff = features[-3].decision_timestamp
    changed = [dict(row) for row in binance]
    for row in changed:
        if row["timestamp"] >= cutoff:
            row["taker_buy_quote_volume"] = row["quote_volume"]
    changed_features, _ = build_weekly_features(changed, kraken, prices)
    assert [feature for feature in changed_features if feature.decision_timestamp <= cutoff] == [
        feature for feature in features if feature.decision_timestamp <= cutoff
    ]


def test_outcomes_enter_one_hour_after_decision_and_exit_next_week() -> None:
    binance, kraken, prices = _inputs()
    features, _ = build_weekly_features(binance, kraken, prices)
    start = features[0].decision_timestamp
    end = features[20].decision_timestamp + 2 * WEEK_SECONDS
    outcomes, diagnostics = build_outcomes(
        features, prices, segment_start=start, segment_end=end
    )
    assert outcomes["all_weeks"]
    first = outcomes["all_weeks"][0]
    assert first.entry_timestamp == first.event_timestamp + HOUR_SECONDS
    assert first.exit_timestamp == first.entry_timestamp + WEEK_SECONDS
    assert diagnostics["eligible_outcomes"] == len(outcomes["all_weeks"])


def _outcome(timestamp: int, value: float, decile: int) -> TradeOutcome:
    return TradeOutcome(
        event_timestamp=timestamp,
        entry_timestamp=timestamp + HOUR_SECONDS,
        exit_timestamp=timestamp + HOUR_SECONDS + WEEK_SECONDS,
        volatility_decile=decile,
        gross_return=value,
    )


def test_stratified_permutation_is_reproducible() -> None:
    start = 1_704_067_200
    all_weeks = [
        _outcome(start + index * WEEK_SECONDS, index / 10_000.0, index % 4)
        for index in range(80)
    ]
    signals = all_weeks[::2]
    first = stratified_permutation_test(signals, all_weeks, replications=100)
    second = stratified_permutation_test(signals, all_weeks, replications=100)
    assert first == second
    assert first["replications"] == 100


def test_analysis_passes_only_when_every_gate_passes() -> None:
    start = 1_704_067_200
    end = 1_767_225_600
    all_weeks = [
        _outcome(
            start + index * WEEK_SECONDS,
            0.04 if index < 80 and index % 2 == 0 else 0.001,
            index % 10,
        )
        for index in range(100)
    ]
    combined = [
        _outcome(start + index * 2 * WEEK_SECONDS, 0.04, index % 10)
        for index in range(40)
    ]
    outcomes = {
        "all_weeks": all_weeks,
        "combined": combined,
        "binance_only": [
            _outcome(item.event_timestamp, 0.02, item.volatility_decile)
            for item in combined
        ],
        "kraken_only": [
            _outcome(item.event_timestamp, 0.015, item.volatility_decile)
            for item in combined
        ],
        "momentum": [
            _outcome(item.event_timestamp, 0.005, item.volatility_decile)
            for item in combined
        ],
    }
    with (
        patch(
            "src.research.cross_venue_order_flow.block_bootstrap_lower_bound",
            return_value=0.01,
        ),
        patch(
            "src.research.cross_venue_order_flow.stratified_permutation_test",
            return_value={
                "replications": 2_000,
                "permuted_mean": 0.0,
                "empirical_p_value": 0.001,
            },
        ),
    ):
        result = analyze_segment(
            outcomes,
            segment_start=start,
            segment_end=end,
            required_years=(2024, 2025),
            data_quality_passed=True,
        )
    assert result["status"] == "pass"
    assert all(result["gates"].values())
