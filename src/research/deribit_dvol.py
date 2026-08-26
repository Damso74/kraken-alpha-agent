"""Causal research harness for preregistered hypothesis H-DV-001."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DAY_SECONDS = 86_400
HOUR_SECONDS = 3_600
ENTRY_DELAY_SECONDS = DAY_SECONDS + HOUR_SECONDS
HOLD_SECONDS = 7 * DAY_SECONDS
VOV_RETURN_DAYS = 7
VOV_HISTORY_DAYS = 365
MIN_HISTORY_COVERAGE = 0.95
MIN_HISTORY_POINTS = math.ceil(VOV_HISTORY_DAYS * MIN_HISTORY_COVERAGE)
PRIMARY_COST_BPS = 50.0
STRESS_COST_BPS = 100.0
NOTIONAL_USD = 1_000.0
MIN_TEST_TRADES = 30
PLACEBO_REPLICATIONS = 2_000
BOOTSTRAP_REPLICATIONS = 10_000
RANDOM_SEED = 20_260_826
FAMILYWISE_P_THRESHOLD = 0.025


@dataclass(frozen=True)
class DvolBar:
    timestamp: int
    close: float


@dataclass(frozen=True)
class PriceBar:
    timestamp: int
    open: float


@dataclass(frozen=True)
class DailyFeature:
    timestamp: int
    vov7: float
    q90: float
    volatility_30d: float
    volatility_decile: int
    is_signal: bool


@dataclass(frozen=True)
class TradeOutcome:
    event_timestamp: int
    entry_timestamp: int
    exit_timestamp: int
    volatility_decile: int
    entry_price: float
    exit_price: float
    gross_return: float

    def net_return(self, cost_bps: float) -> float:
        return self.gross_return - cost_bps / 10_000.0


def _nearest_rank(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("cannot calculate a quantile from an empty sequence")
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def _sample_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        raise ValueError("sample standard deviation needs at least two values")
    return statistics.stdev(values)


def _consecutive(values: Sequence[int], step: int) -> bool:
    return all(
        right - left == step
        for left, right in zip(values, values[1:], strict=False)
    )


def _parse_dvol(rows: Sequence[dict[str, Any]]) -> list[DvolBar]:
    parsed: list[DvolBar] = []
    for row in rows:
        timestamp = row.get("timestamp")
        close = row.get("close")
        if not isinstance(timestamp, int) or isinstance(close, bool):
            continue
        try:
            numeric_close = float(close)
        except (TypeError, ValueError):
            continue
        if timestamp % DAY_SECONDS or not math.isfinite(numeric_close) or numeric_close <= 0:
            continue
        parsed.append(DvolBar(timestamp, numeric_close))
    return sorted({bar.timestamp: bar for bar in parsed}.values(), key=lambda bar: bar.timestamp)


def _parse_prices(rows: Sequence[dict[str, Any]]) -> dict[int, PriceBar]:
    parsed: dict[int, PriceBar] = {}
    for row in rows:
        timestamp = row.get("timestamp")
        open_price = row.get("open")
        if not isinstance(timestamp, int) or isinstance(open_price, bool):
            continue
        try:
            numeric_open = float(open_price)
        except (TypeError, ValueError):
            continue
        if (
            timestamp % HOUR_SECONDS
            or not math.isfinite(numeric_open)
            or numeric_open <= 0
        ):
            continue
        parsed[timestamp] = PriceBar(timestamp, numeric_open)
    return parsed


def _causal_decile(value: float, history: Sequence[float]) -> int:
    thresholds = [_nearest_rank(history, index / 10.0) for index in range(1, 10)]
    return sum(value > threshold for threshold in thresholds)


def build_daily_features(
    dvol_rows: Sequence[dict[str, Any]],
    price_rows: Sequence[dict[str, Any]],
) -> tuple[list[DailyFeature], dict[str, int]]:
    """Build H-DV-001 features using only observations strictly prior to each threshold."""

    dvol = _parse_dvol(dvol_rows)
    prices = _parse_prices(price_rows)
    raw_vov: list[tuple[int, float]] = []
    invalid_windows = 0
    for index in range(VOV_RETURN_DAYS, len(dvol)):
        window = dvol[index - VOV_RETURN_DAYS : index + 1]
        timestamps = [bar.timestamp for bar in window]
        if not _consecutive(timestamps, DAY_SECONDS):
            invalid_windows += 1
            continue
        returns = [
            math.log(window[position].close / window[position - 1].close)
            for position in range(1, len(window))
        ]
        raw_vov.append((window[-1].timestamp, _sample_stdev(returns)))

    price_volatility: dict[int, float] = {}
    raw_days = [timestamp for timestamp, _value in raw_vov]
    for day in raw_days:
        timestamps = [day - offset * DAY_SECONDS + HOUR_SECONDS for offset in range(30, -1, -1)]
        if any(timestamp not in prices for timestamp in timestamps):
            continue
        price_values = [prices[timestamp].open for timestamp in timestamps]
        returns = [
            math.log(price_values[position] / price_values[position - 1])
            for position in range(1, len(price_values))
        ]
        price_volatility[day] = _sample_stdev(returns)

    features: list[DailyFeature] = []
    vov_history: list[tuple[int, float]] = []
    volatility_history: list[tuple[int, float]] = []
    for timestamp, vov7 in raw_vov:
        cutoff = timestamp - VOV_HISTORY_DAYS * DAY_SECONDS
        vov_history = [(ts, value) for ts, value in vov_history if ts >= cutoff]
        volatility_history = [
            (ts, value) for ts, value in volatility_history if ts >= cutoff
        ]
        volatility = price_volatility.get(timestamp)
        if (
            volatility is not None
            and len(vov_history) >= MIN_HISTORY_POINTS
            and len(volatility_history) >= MIN_HISTORY_POINTS
        ):
            prior_vov = [value for _ts, value in vov_history]
            prior_volatility = [value for _ts, value in volatility_history]
            q90 = _nearest_rank(prior_vov, 0.90)
            features.append(
                DailyFeature(
                    timestamp=timestamp,
                    vov7=vov7,
                    q90=q90,
                    volatility_30d=volatility,
                    volatility_decile=_causal_decile(volatility, prior_volatility),
                    is_signal=vov7 >= q90,
                )
            )
        vov_history.append((timestamp, vov7))
        if volatility is not None:
            volatility_history.append((timestamp, volatility))

    diagnostics = {
        "dvol_rows": len(dvol),
        "raw_vov_points": len(raw_vov),
        "price_volatility_points": len(price_volatility),
        "eligible_points": len(features),
        "invalid_vov_windows": invalid_windows,
    }
    return features, diagnostics


def build_outcomes(
    features: Sequence[DailyFeature],
    price_rows: Sequence[dict[str, Any]],
    *,
    segment_start: int,
    segment_end: int,
) -> tuple[list[TradeOutcome], list[TradeOutcome], dict[str, int]]:
    """Create non-overlapping signal trades and all eligible placebo candidates."""

    prices = _parse_prices(price_rows)
    signals: list[TradeOutcome] = []
    placebo: list[TradeOutcome] = []
    last_exit = -1
    skipped_missing_price = 0
    skipped_overlap = 0
    for feature in features:
        if not (segment_start <= feature.timestamp < segment_end):
            continue
        entry_timestamp = feature.timestamp + ENTRY_DELAY_SECONDS
        exit_timestamp = entry_timestamp + HOLD_SECONDS
        if exit_timestamp >= segment_end:
            continue
        entry = prices.get(entry_timestamp)
        exit_bar = prices.get(exit_timestamp)
        if entry is None or exit_bar is None:
            skipped_missing_price += 1
            continue
        outcome = TradeOutcome(
            event_timestamp=feature.timestamp,
            entry_timestamp=entry_timestamp,
            exit_timestamp=exit_timestamp,
            volatility_decile=feature.volatility_decile,
            entry_price=entry.open,
            exit_price=exit_bar.open,
            gross_return=exit_bar.open / entry.open - 1.0,
        )
        if feature.is_signal:
            if entry_timestamp < last_exit:
                skipped_overlap += 1
                continue
            signals.append(outcome)
            last_exit = exit_timestamp
        else:
            placebo.append(outcome)
    return signals, placebo, {
        "signals": len(signals),
        "placebo_candidates": len(placebo),
        "skipped_missing_price": skipped_missing_price,
        "skipped_signal_overlap": skipped_overlap,
    }


def _summary(
    outcomes: Sequence[TradeOutcome], cost_bps: float
) -> dict[str, float | int | None]:
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
        "pnl_usd": sum(value * NOTIONAL_USD for value in returns),
        "best_return": max(returns),
        "worst_return": min(returns),
    }


def block_bootstrap_lower_bound(
    outcomes: Sequence[TradeOutcome],
    *,
    segment_start: int,
    segment_end: int,
    cost_bps: float = PRIMARY_COST_BPS,
    replications: int = BOOTSTRAP_REPLICATIONS,
    seed: int = RANDOM_SEED,
) -> float | None:
    if not outcomes or segment_end <= segment_start:
        return None
    block_seconds = 28 * DAY_SECONDS
    block_count = math.ceil((segment_end - segment_start) / block_seconds)
    blocks: list[list[float]] = [[] for _ in range(block_count)]
    for outcome in outcomes:
        index = min(
            block_count - 1,
            max(0, (outcome.event_timestamp - segment_start) // block_seconds),
        )
        blocks[index].append(outcome.net_return(cost_bps))
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(replications):
        sampled: list[float] = []
        for _block in blocks:
            sampled.extend(rng.choice(blocks))
        if sampled:
            means.append(statistics.fmean(sampled))
    if not means:
        return None
    means.sort()
    return means[max(0, math.floor(0.05 * (len(means) - 1)))]


def _overlaps(candidate: TradeOutcome, selected: Sequence[TradeOutcome]) -> bool:
    return any(
        candidate.entry_timestamp < other.exit_timestamp
        and candidate.exit_timestamp > other.entry_timestamp
        for other in selected
    )


def matched_placebo_test(
    signals: Sequence[TradeOutcome],
    placebo: Sequence[TradeOutcome],
    *,
    cost_bps: float = PRIMARY_COST_BPS,
    replications: int = PLACEBO_REPLICATIONS,
    seed: int = RANDOM_SEED,
) -> dict[str, float | int | None]:
    if not signals or not placebo:
        return {"replications": 0, "matched_mean": None, "empirical_p_value": None}
    pools: dict[tuple[int, int], list[TradeOutcome]] = {}
    for outcome in placebo:
        year = datetime.fromtimestamp(outcome.event_timestamp, tz=UTC).year
        pools.setdefault((year, outcome.volatility_decile), []).append(outcome)
    rng = random.Random(seed)
    observed = statistics.fmean(
        outcome.net_return(cost_bps) for outcome in signals
    )
    placebo_means: list[float] = []
    ordered_signals = sorted(
        signals,
        key=lambda outcome: len(
            pools.get(
                (
                    datetime.fromtimestamp(outcome.event_timestamp, tz=UTC).year,
                    outcome.volatility_decile,
                ),
                [],
            )
        ),
    )
    for _ in range(replications):
        selected: list[TradeOutcome] = []
        valid = True
        for signal in ordered_signals:
            key = (
                datetime.fromtimestamp(signal.event_timestamp, tz=UTC).year,
                signal.volatility_decile,
            )
            candidates = list(pools.get(key, ()))
            rng.shuffle(candidates)
            candidate = next(
                (
                    item
                    for item in candidates
                    if item not in selected and not _overlaps(item, selected)
                ),
                None,
            )
            if candidate is None:
                valid = False
                break
            selected.append(candidate)
        if valid:
            placebo_means.append(
                statistics.fmean(item.net_return(cost_bps) for item in selected)
            )
    if len(placebo_means) != replications:
        return {
            "replications": len(placebo_means),
            "matched_mean": (
                statistics.fmean(placebo_means) if placebo_means else None
            ),
            "empirical_p_value": None,
        }
    exceedances = sum(value >= observed for value in placebo_means)
    return {
        "replications": replications,
        "matched_mean": statistics.fmean(placebo_means),
        "empirical_p_value": (exceedances + 1) / (replications + 1),
    }


def _quarter(timestamp: int) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=UTC)
    return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"


def quarterly_robustness(
    outcomes: Sequence[TradeOutcome],
    *,
    required_years: Sequence[int],
    cost_bps: float = PRIMARY_COST_BPS,
) -> dict[str, Any]:
    by_year: dict[int, float] = {year: 0.0 for year in required_years}
    by_quarter: dict[str, float] = {
        f"{year}-Q{quarter}": 0.0
        for year in required_years
        for quarter in range(1, 5)
    }
    positive_by_quarter = dict.fromkeys(by_quarter, 0.0)
    total = 0.0
    for outcome in outcomes:
        value = outcome.net_return(cost_bps)
        year = datetime.fromtimestamp(outcome.event_timestamp, tz=UTC).year
        quarter = _quarter(outcome.event_timestamp)
        if year in by_year:
            by_year[year] += value
        if quarter in by_quarter:
            by_quarter[quarter] += value
            positive_by_quarter[quarter] += max(0.0, value)
        total += value
    leave_one_out = {
        quarter: total - value for quarter, value in by_quarter.items()
    }
    positive_total = sum(positive_by_quarter.values())
    max_positive_share = (
        max(positive_by_quarter.values()) / positive_total if positive_total > 0 else None
    )
    return {
        "pnl_return_by_year": by_year,
        "pnl_return_by_quarter": by_quarter,
        "leave_one_quarter_out": leave_one_out,
        "positive_each_year": bool(by_year)
        and all(value > 0 for value in by_year.values()),
        "positive_leave_one_quarter_out": bool(leave_one_out)
        and all(value > 0 for value in leave_one_out.values()),
        "max_positive_gain_share": max_positive_share,
        "acceptable_quarter_concentration": max_positive_share is not None
        and max_positive_share <= 0.50,
    }


def analyze_segment(
    signals: Sequence[TradeOutcome],
    placebo: Sequence[TradeOutcome],
    *,
    segment_start: int,
    segment_end: int,
    required_years: Sequence[int],
    data_quality_passed: bool,
) -> dict[str, Any]:
    primary = _summary(signals, PRIMARY_COST_BPS)
    stress = _summary(signals, STRESS_COST_BPS)
    lower_bound = block_bootstrap_lower_bound(
        signals,
        segment_start=segment_start,
        segment_end=segment_end,
    )
    matched = matched_placebo_test(signals, placebo)
    quarterly = quarterly_robustness(signals, required_years=required_years)
    p_value = matched["empirical_p_value"]
    gates = {
        "min_30_trades": len(signals) >= MIN_TEST_TRADES,
        "positive_pnl": float(primary["pnl_usd"]) > 0,
        "positive_mean": primary["mean_return"] is not None
        and float(primary["mean_return"]) > 0,
        "win_rate_50pct": primary["win_rate"] is not None
        and float(primary["win_rate"]) >= 0.50,
        "bootstrap_lower_bound_positive": lower_bound is not None and lower_bound > 0,
        "beats_matched_placebo_bonferroni": p_value is not None
        and float(p_value) <= FAMILYWISE_P_THRESHOLD,
        "positive_at_100bps": float(stress["pnl_usd"]) > 0,
        "positive_each_year": bool(quarterly["positive_each_year"]),
        "positive_leave_one_quarter_out": bool(
            quarterly["positive_leave_one_quarter_out"]
        ),
        "acceptable_quarter_concentration": bool(
            quarterly["acceptable_quarter_concentration"]
        ),
        "data_quality": bool(data_quality_passed),
    }
    passed = all(gates.values())
    status = (
        "insufficient_power"
        if len(signals) < MIN_TEST_TRADES
        else "pass" if passed else "not_supported"
    )
    return {
        "status": status,
        "passed": passed,
        "primary_cost_bps": PRIMARY_COST_BPS,
        "primary": primary,
        "stress_100bps": stress,
        "bootstrap_lower_95_one_sided": lower_bound,
        "matched_placebo": matched,
        "quarterly_robustness": quarterly,
        "gates": gates,
    }
