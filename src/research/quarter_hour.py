"""Preregistered quarter-hour order-flow research (H-QH-001).

Pure research functions only: no network access and no order execution.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

MINUTE_SECONDS = 60
DAY_SECONDS = 86400
LOOKBACK_DAYS = 180
LOOKBACK_SECONDS = LOOKBACK_DAYS * DAY_SECONDS
MIN_HISTORY_COVERAGE = 0.95
SIGNAL_QUANTILE = 0.90
PRIMARY_PHASE_MINUTE = 0
PLACEBO_PHASE_MINUTE = 7
ENTRY_OFFSET_MINUTES = 1
HOLD_MINUTES = 480
EXIT_OFFSET_MINUTES = ENTRY_OFFSET_MINUTES + HOLD_MINUTES
PRIMARY_COST_BPS = 20.0
STRESS_COST_BPS = 40.0
NOTIONAL_USD = 1000.0
MIN_TEST_TRADES = 300
FAMILY_ALPHA = 0.05 / 3.0
BOOTSTRAP_REPLICATIONS = 10_000
PLACEBO_REPLICATIONS = 5_000
RANDOM_SEED = 20260826
FUNDING_SETTLEMENT_HOURS_UTC = frozenset({0, 8, 16})


@dataclass(frozen=True)
class MinuteBar:
    timestamp: int
    open: float
    close: float
    aggressor_differential: float


@dataclass(frozen=True)
class SignalEvent:
    timestamp: int
    phase_minute: int
    aggressor_differential: float
    causal_threshold: float


@dataclass(frozen=True)
class TradeOutcome:
    event_timestamp: int
    entry_timestamp: int
    exit_timestamp: int
    entry_price: float
    exit_price: float
    gross_return: float

    def net_return(self, cost_bps: float) -> float:
        return self.gross_return - cost_bps / 10_000.0


def _row_map(rows: Sequence[dict[str, Any]], field: str) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            timestamp = int(row["timestamp"])
            float(row[field])
        except (KeyError, TypeError, ValueError):
            continue
        result[timestamp] = dict(row)
    return result


def align_minute_bars(
    candles: Sequence[dict[str, Any]],
    aggressor: Sequence[dict[str, Any]],
) -> tuple[list[MinuteBar], dict[str, int]]:
    """Align exact minute buckets and reject invalid/off-grid rows."""
    candle_map = _row_map(candles, "open")
    aggressor_map = _row_map(aggressor, "aggressor_differential")
    common = sorted(set(candle_map) & set(aggressor_map))
    bars: list[MinuteBar] = []
    invalid = 0
    off_grid = 0
    for timestamp in common:
        if timestamp % MINUTE_SECONDS:
            off_grid += 1
            continue
        try:
            open_price = float(candle_map[timestamp]["open"])
            close_price = float(candle_map[timestamp]["close"])
            differential = float(
                aggressor_map[timestamp]["aggressor_differential"]
            )
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        if (
            not all(math.isfinite(value) for value in (open_price, close_price, differential))
            or open_price <= 0
            or close_price <= 0
        ):
            invalid += 1
            continue
        bars.append(MinuteBar(timestamp, open_price, close_price, differential))
    return bars, {
        "candles": len(candle_map),
        "aggressor": len(aggressor_map),
        "common": len(common),
        "valid": len(bars),
        "invalid": invalid,
        "off_grid": off_grid,
    }


def nearest_rank(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("nearest_rank requires values")
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def week_start_utc(timestamp: int) -> int:
    dt = datetime.fromtimestamp(timestamp, tz=UTC)
    day_start = int(datetime(dt.year, dt.month, dt.day, tzinfo=UTC).timestamp())
    return day_start - dt.weekday() * DAY_SECONDS


def build_causal_weekly_thresholds(
    bars: Sequence[MinuteBar],
    *,
    segment_start: int,
    segment_end: int,
) -> tuple[dict[int, float], dict[str, Any]]:
    """Compute one weekly q90 from the 180 days ending before that week.

    Fixing the threshold for a UTC week makes causality explicit: no observation
    from the current week can influence any signal in that week.
    """
    ordered = sorted(bars, key=lambda item: item.timestamp)
    expected = LOOKBACK_DAYS * 24 * 60
    first_week = week_start_utc(segment_start)
    last_week = week_start_utc(segment_end - 1)
    week_starts = range(first_week, last_week + 1, 7 * DAY_SECONDS)
    thresholds: dict[int, float] = {}
    coverages: dict[int, float] = {}
    for week_start in week_starts:
        window_start = week_start - LOOKBACK_SECONDS
        values = [
            bar.aggressor_differential
            for bar in ordered
            if window_start <= bar.timestamp < week_start
        ]
        coverage = len(values) / expected
        coverages[week_start] = coverage
        if coverage >= MIN_HISTORY_COVERAGE:
            thresholds[week_start] = nearest_rank(values, SIGNAL_QUANTILE)
    return thresholds, {
        "weeks_expected": len(coverages),
        "weeks_with_threshold": len(thresholds),
        "min_coverage": min(coverages.values()) if coverages else 0.0,
        "coverage_by_week": {str(key): value for key, value in coverages.items()},
    }


def generate_events(
    bars: Sequence[MinuteBar],
    thresholds: dict[int, float],
    *,
    segment_start: int,
    segment_end: int,
    phase_minute: int,
) -> list[SignalEvent]:
    if not 0 <= phase_minute < 15:
        raise ValueError("phase_minute must be in [0, 14]")
    events: list[SignalEvent] = []
    last_event = -10**18
    for bar in sorted(bars, key=lambda item: item.timestamp):
        if not segment_start <= bar.timestamp < segment_end:
            continue
        event_time = datetime.fromtimestamp(bar.timestamp, tz=UTC)
        minute = event_time.minute
        if minute % 15 != phase_minute:
            continue
        # The preregistration excludes the three daily funding-settlement
        # windows.  Apply the same hour exclusion to the primary phase and its
        # +7 minute placebo so the comparison remains time-of-day matched.
        if event_time.hour in FUNDING_SETTLEMENT_HOURS_UTC:
            continue
        threshold = thresholds.get(week_start_utc(bar.timestamp))
        if threshold is None:
            continue
        if bar.aggressor_differential <= max(0.0, threshold):
            continue
        if bar.timestamp - last_event < HOLD_MINUTES * MINUTE_SECONDS:
            continue
        events.append(
            SignalEvent(
                timestamp=bar.timestamp,
                phase_minute=phase_minute,
                aggressor_differential=bar.aggressor_differential,
                causal_threshold=threshold,
            )
        )
        last_event = bar.timestamp
    return events


def build_trade_outcomes(
    events: Sequence[SignalEvent],
    bars: Sequence[MinuteBar],
    *,
    segment_start: int,
    segment_end: int,
) -> list[TradeOutcome]:
    by_timestamp = {bar.timestamp: bar for bar in bars}
    outcomes: list[TradeOutcome] = []
    for event in events:
        if not segment_start <= event.timestamp < segment_end:
            continue
        entry_timestamp = event.timestamp + ENTRY_OFFSET_MINUTES * MINUTE_SECONDS
        exit_timestamp = event.timestamp + EXIT_OFFSET_MINUTES * MINUTE_SECONDS
        if exit_timestamp >= segment_end:
            continue
        entry = by_timestamp.get(entry_timestamp)
        exit_bar = by_timestamp.get(exit_timestamp)
        if entry is None or exit_bar is None:
            continue
        outcomes.append(
            TradeOutcome(
                event_timestamp=event.timestamp,
                entry_timestamp=entry_timestamp,
                exit_timestamp=exit_timestamp,
                entry_price=entry.open,
                exit_price=exit_bar.open,
                gross_return=exit_bar.open / entry.open - 1.0,
            )
        )
    return outcomes


def _summary(outcomes: Sequence[TradeOutcome], cost_bps: float) -> dict[str, Any]:
    returns = [outcome.net_return(cost_bps) for outcome in outcomes]
    if not returns:
        return {
            "trade_count": 0,
            "mean_return": None,
            "median_return": None,
            "win_rate": None,
            "pnl_usd": 0.0,
            "best_return": None,
            "worst_return": None,
        }
    return {
        "trade_count": len(returns),
        "mean_return": statistics.fmean(returns),
        "median_return": statistics.median(returns),
        "win_rate": sum(value > 0 for value in returns) / len(returns),
        "pnl_usd": sum(returns) * NOTIONAL_USD,
        "best_return": max(returns),
        "worst_return": min(returns),
    }


def block_bootstrap_lower_bound(
    outcomes: Sequence[TradeOutcome],
    *,
    cost_bps: float = PRIMARY_COST_BPS,
    replications: int = BOOTSTRAP_REPLICATIONS,
    seed: int = RANDOM_SEED,
) -> float | None:
    if not outcomes:
        return None
    by_day: dict[int, list[float]] = {}
    for outcome in outcomes:
        day = outcome.event_timestamp // DAY_SECONDS
        by_day.setdefault(day, []).append(outcome.net_return(cost_bps))
    blocks = list(by_day.values())
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(replications):
        sampled: list[float] = []
        for _block in blocks:
            sampled.extend(rng.choice(blocks))
        means.append(statistics.fmean(sampled))
    means.sort()
    return means[max(0, math.floor(0.05 * (len(means) - 1)))]


def matched_placebo_test(
    primary: Sequence[TradeOutcome],
    placebo: Sequence[TradeOutcome],
    *,
    cost_bps: float = PRIMARY_COST_BPS,
    replications: int = PLACEBO_REPLICATIONS,
    seed: int = RANDOM_SEED,
) -> dict[str, Any]:
    if not primary or not placebo:
        return {"replications": 0, "matched_mean": None, "empirical_p_value": None}
    pools: dict[tuple[int, int], list[TradeOutcome]] = {}
    for outcome in placebo:
        dt = datetime.fromtimestamp(outcome.event_timestamp, tz=UTC)
        pools.setdefault((dt.year, dt.month), []).append(outcome)
    all_placebo = list(placebo)
    observed = statistics.fmean(
        outcome.net_return(cost_bps) for outcome in primary
    )
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(replications):
        sampled: list[float] = []
        for outcome in primary:
            dt = datetime.fromtimestamp(outcome.event_timestamp, tz=UTC)
            pool = pools.get((dt.year, dt.month), all_placebo)
            sampled.append(rng.choice(pool).net_return(cost_bps))
        means.append(statistics.fmean(sampled))
    exceedances = sum(value >= observed for value in means)
    return {
        "replications": replications,
        "matched_mean": statistics.fmean(means),
        "empirical_p_value": (exceedances + 1) / (replications + 1),
    }


def _robustness(
    outcomes: Sequence[TradeOutcome],
    *,
    cost_bps: float,
    segment_start: int,
    segment_end: int,
) -> dict[str, Any]:
    values = [(item, item.net_return(cost_bps)) for item in outcomes]
    midpoint = segment_start + (segment_end - segment_start) // 2
    first_half = [value for item, value in values if item.event_timestamp < midpoint]
    second_half = [value for item, value in values if item.event_timestamp >= midpoint]
    months: dict[tuple[int, int], list[float]] = {}
    quarters: dict[tuple[int, int], list[float]] = {}
    for item, value in values:
        dt = datetime.fromtimestamp(item.event_timestamp, tz=UTC)
        months.setdefault((dt.year, dt.month), []).append(value)
        quarters.setdefault((dt.year, (dt.month - 1) // 3 + 1), []).append(value)
    month_totals = {key: sum(group) for key, group in months.items()}
    best_month = max(month_totals, key=month_totals.get) if month_totals else None
    without_best = [
        value
        for item, value in values
        if best_month
        != (
            datetime.fromtimestamp(item.event_timestamp, tz=UTC).year,
            datetime.fromtimestamp(item.event_timestamp, tz=UTC).month,
        )
    ]
    absolute_total = sum(abs(value) for _, value in values)
    quarter_abs_share = (
        max((abs(sum(group)) for group in quarters.values()), default=0.0)
        / absolute_total
        if absolute_total
        else 1.0
    )
    max_trade_share = (
        max((abs(value) for _, value in values), default=0.0) / absolute_total
        if absolute_total
        else 1.0
    )
    return {
        "first_half_pnl_usd": sum(first_half) * NOTIONAL_USD,
        "second_half_pnl_usd": sum(second_half) * NOTIONAL_USD,
        "best_month": list(best_month) if best_month else None,
        "pnl_without_best_month_usd": sum(without_best) * NOTIONAL_USD,
        "dominant_quarter_abs_share": quarter_abs_share,
        "max_trade_abs_share": max_trade_share,
    }


def analyze_segment(
    primary: Sequence[TradeOutcome],
    placebo: Sequence[TradeOutcome],
    *,
    segment_start: int,
    segment_end: int,
    data_quality_passed: bool,
) -> dict[str, Any]:
    primary_summary = _summary(primary, PRIMARY_COST_BPS)
    stress = {
        str(cost): _summary(primary, cost)
        for cost in (PRIMARY_COST_BPS, STRESS_COST_BPS)
    }
    placebo_summary = _summary(placebo, PRIMARY_COST_BPS)
    bootstrap = block_bootstrap_lower_bound(primary)
    matched = matched_placebo_test(primary, placebo)
    robustness = _robustness(
        primary,
        cost_bps=PRIMARY_COST_BPS,
        segment_start=segment_start,
        segment_end=segment_end,
    )
    mean_return = primary_summary["mean_return"]
    matched_mean = matched["matched_mean"]
    p_value = matched["empirical_p_value"]
    gates = {
        "min_300_trades": len(primary) >= MIN_TEST_TRADES,
        "positive_pnl": float(primary_summary["pnl_usd"]) > 0,
        "positive_mean": mean_return is not None and float(mean_return) > 0,
        "win_rate_50pct": primary_summary["win_rate"] is not None
        and float(primary_summary["win_rate"]) >= 0.50,
        "bootstrap_lower_bound_positive": bootstrap is not None and bootstrap > 0,
        "beats_matched_off_quarter_placebo": mean_return is not None
        and matched_mean is not None
        and float(mean_return) > float(matched_mean)
        and p_value is not None
        and float(p_value) <= FAMILY_ALPHA,
        "positive_at_40bps": float(stress[str(STRESS_COST_BPS)]["pnl_usd"]) > 0,
        "both_time_halves_positive": robustness["first_half_pnl_usd"] > 0
        and robustness["second_half_pnl_usd"] > 0,
        "positive_without_best_month": robustness["pnl_without_best_month_usd"] > 0,
        "acceptable_concentration": robustness["dominant_quarter_abs_share"] <= 0.40
        and robustness["max_trade_abs_share"] <= 0.10,
        "data_quality": bool(data_quality_passed),
    }
    passed = all(gates.values())
    status = (
        "insufficient_power"
        if len(primary) < MIN_TEST_TRADES
        else "pass" if passed else "not_supported"
    )
    return {
        "status": status,
        "passed": passed,
        "primary_cost_bps": PRIMARY_COST_BPS,
        "family_alpha": FAMILY_ALPHA,
        "quarter_hour": primary_summary,
        "off_quarter_placebo": placebo_summary,
        "stress_costs": stress,
        "bootstrap_lower_95_one_sided": bootstrap,
        "matched_placebo": matched,
        "robustness": robustness,
        "gates": gates,
    }


def event_to_dict(event: SignalEvent) -> dict[str, Any]:
    return asdict(event)


__all__ = [
    "MinuteBar",
    "SignalEvent",
    "TradeOutcome",
    "align_minute_bars",
    "analyze_segment",
    "block_bootstrap_lower_bound",
    "build_causal_weekly_thresholds",
    "build_trade_outcomes",
    "generate_events",
    "matched_placebo_test",
    "nearest_rank",
    "week_start_utc",
]
