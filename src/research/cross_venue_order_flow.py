"""Causal weekly harness for preregistered hypothesis H-OF-001."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DAY_SECONDS = 86_400
WEEK_SECONDS = 7 * DAY_SECONDS
HOUR_SECONDS = 3_600
ENTRY_DELAY_SECONDS = HOUR_SECONDS
HOLD_SECONDS = WEEK_SECONDS
VOLATILITY_HISTORY_WEEKS = 52
MIN_VOLATILITY_HISTORY = math.ceil(VOLATILITY_HISTORY_WEEKS * 0.95)
PRIMARY_COST_BPS = 50.0
STRESS_COST_BPS = 100.0
NOTIONAL_USD = 1_000.0
MIN_TEST_TRADES = 30
PLACEBO_REPLICATIONS = 2_000
BOOTSTRAP_REPLICATIONS = 10_000
RANDOM_SEED = 20_260_826
FAMILYWISE_P_THRESHOLD = 0.0166667


@dataclass(frozen=True)
class WeeklyFeature:
    source_week_start: int
    decision_timestamp: int
    binance_imbalance: float
    kraken_imbalance: float
    combined_imbalance: float
    source_week_return: float
    volatility_30d: float
    volatility_decile: int

    @property
    def combined_signal(self) -> bool:
        return self.combined_imbalance > 0

    @property
    def binance_signal(self) -> bool:
        return self.binance_imbalance > 0

    @property
    def kraken_signal(self) -> bool:
        return self.kraken_imbalance > 0

    @property
    def momentum_signal(self) -> bool:
        return self.source_week_return > 0


@dataclass(frozen=True)
class TradeOutcome:
    event_timestamp: int
    entry_timestamp: int
    exit_timestamp: int
    volatility_decile: int
    gross_return: float

    def net_return(self, cost_bps: float) -> float:
        return self.gross_return - cost_bps / 10_000.0


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _nearest_rank(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("empty quantile input")
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def _causal_decile(value: float, history: Sequence[float]) -> int:
    thresholds = [_nearest_rank(history, index / 10.0) for index in range(1, 10)]
    return sum(value > threshold for threshold in thresholds)


def _binance_daily(
    rows: Sequence[dict[str, Any]],
) -> dict[int, tuple[float, float]]:
    result: dict[int, tuple[float, float]] = {}
    for row in rows:
        timestamp = row.get("timestamp")
        quote_volume = _float(row.get("quote_volume"))
        taker_buy = _float(row.get("taker_buy_quote_volume"))
        if (
            not isinstance(timestamp, int)
            or timestamp % DAY_SECONDS
            or quote_volume is None
            or taker_buy is None
            or quote_volume <= 0
            or taker_buy < 0
            or taker_buy > quote_volume
        ):
            continue
        result[timestamp] = (2.0 * taker_buy - quote_volume, quote_volume)
    return result


def _kraken_daily(
    rows: Sequence[dict[str, Any]],
) -> dict[int, tuple[float, float]]:
    result: dict[int, tuple[float, float]] = {}
    for row in rows:
        timestamp = row.get("timestamp")
        buy = _float(row.get("buy_volume"))
        sell = _float(row.get("sell_volume"))
        if (
            not isinstance(timestamp, int)
            or timestamp % DAY_SECONDS
            or buy is None
            or sell is None
            or buy < 0
            or sell < 0
            or buy + sell <= 0
        ):
            continue
        result[timestamp] = (buy - sell, buy + sell)
    return result


def _price_opens(rows: Sequence[dict[str, Any]]) -> dict[int, float]:
    result: dict[int, float] = {}
    for row in rows:
        timestamp = row.get("timestamp")
        price = _float(row.get("open"))
        if (
            isinstance(timestamp, int)
            and timestamp % HOUR_SECONDS == 0
            and price is not None
            and price > 0
        ):
            result[timestamp] = price
    return result


def build_weekly_features(
    binance_rows: Sequence[dict[str, Any]],
    kraken_cvd_rows: Sequence[dict[str, Any]],
    price_rows: Sequence[dict[str, Any]],
) -> tuple[list[WeeklyFeature], dict[str, int]]:
    binance = _binance_daily(binance_rows)
    kraken = _kraken_daily(kraken_cvd_rows)
    prices = _price_opens(price_rows)
    common_days = sorted(set(binance) & set(kraken))
    if not common_days:
        return [], {
            "binance_days": len(binance),
            "kraken_days": len(kraken),
            "common_days": 0,
            "complete_weeks": 0,
            "eligible_weeks": 0,
        }
    first_day = common_days[0]
    first_monday = first_day - datetime.fromtimestamp(first_day, tz=UTC).weekday() * DAY_SECONDS
    last_day = common_days[-1]
    raw_weeks: list[tuple[int, int, float, float, float, float]] = []
    week_start = first_monday
    while week_start + WEEK_SECONDS - DAY_SECONDS <= last_day:
        days = [week_start + index * DAY_SECONDS for index in range(7)]
        if all(day in binance and day in kraken for day in days):
            binance_num = sum(binance[day][0] for day in days)
            binance_den = sum(binance[day][1] for day in days)
            kraken_num = sum(kraken[day][0] for day in days)
            kraken_den = sum(kraken[day][1] for day in days)
            if binance_den > 0 and kraken_den > 0:
                decision = week_start + WEEK_SECONDS
                price_timestamps = [
                    decision - offset * DAY_SECONDS
                    for offset in range(31, 0, -1)
                ]
                if all(timestamp in prices for timestamp in price_timestamps):
                    price_values = [prices[timestamp] for timestamp in price_timestamps]
                    returns = [
                        math.log(price_values[index] / price_values[index - 1])
                        for index in range(1, len(price_values))
                    ]
                    volatility = statistics.stdev(returns)
                    source_open = prices.get(week_start)
                    decision_open = prices.get(decision)
                    if source_open is None or decision_open is None:
                        week_start += WEEK_SECONDS
                        continue
                    raw_weeks.append(
                        (
                            week_start,
                            decision,
                            binance_num / binance_den,
                            kraken_num / kraken_den,
                            decision_open / source_open - 1.0,
                            volatility,
                        )
                    )
        week_start += WEEK_SECONDS

    features: list[WeeklyFeature] = []
    volatility_history: list[tuple[int, float]] = []
    for (
        week_start,
        decision,
        binance_value,
        kraken_value,
        source_return,
        volatility,
    ) in raw_weeks:
        cutoff = decision - VOLATILITY_HISTORY_WEEKS * WEEK_SECONDS
        volatility_history = [
            (timestamp, value)
            for timestamp, value in volatility_history
            if timestamp >= cutoff
        ]
        if len(volatility_history) >= MIN_VOLATILITY_HISTORY:
            prior = [value for _timestamp, value in volatility_history]
            features.append(
                WeeklyFeature(
                    source_week_start=week_start,
                    decision_timestamp=decision,
                    binance_imbalance=binance_value,
                    kraken_imbalance=kraken_value,
                    combined_imbalance=(binance_value + kraken_value) / 2.0,
                    source_week_return=source_return,
                    volatility_30d=volatility,
                    volatility_decile=_causal_decile(volatility, prior),
                )
            )
        volatility_history.append((decision, volatility))
    return features, {
        "binance_days": len(binance),
        "kraken_days": len(kraken),
        "common_days": len(common_days),
        "complete_weeks": len(raw_weeks),
        "eligible_weeks": len(features),
    }


def build_outcomes(
    features: Sequence[WeeklyFeature],
    price_rows: Sequence[dict[str, Any]],
    *,
    segment_start: int,
    segment_end: int,
) -> tuple[dict[str, list[TradeOutcome]], dict[str, int]]:
    prices = _price_opens(price_rows)
    outcomes: dict[str, list[TradeOutcome]] = {
        "all_weeks": [],
        "combined": [],
        "binance_only": [],
        "kraken_only": [],
        "momentum": [],
    }
    missing_price = 0
    embargoed = 0
    for feature in features:
        event = feature.decision_timestamp
        if not (segment_start <= event < segment_end):
            continue
        entry_timestamp = event + ENTRY_DELAY_SECONDS
        exit_timestamp = entry_timestamp + HOLD_SECONDS
        if exit_timestamp >= segment_end:
            embargoed += 1
            continue
        entry = prices.get(entry_timestamp)
        exit_price = prices.get(exit_timestamp)
        if entry is None or exit_price is None:
            missing_price += 1
            continue
        outcome = TradeOutcome(
            event_timestamp=event,
            entry_timestamp=entry_timestamp,
            exit_timestamp=exit_timestamp,
            volatility_decile=feature.volatility_decile,
            gross_return=exit_price / entry - 1.0,
        )
        outcomes["all_weeks"].append(outcome)
        if feature.combined_signal:
            outcomes["combined"].append(outcome)
        if feature.binance_signal:
            outcomes["binance_only"].append(outcome)
        if feature.kraken_signal:
            outcomes["kraken_only"].append(outcome)
        if feature.momentum_signal:
            outcomes["momentum"].append(outcome)
    return outcomes, {
        "eligible_outcomes": len(outcomes["all_weeks"]),
        "combined_signals": len(outcomes["combined"]),
        "binance_signals": len(outcomes["binance_only"]),
        "kraken_signals": len(outcomes["kraken_only"]),
        "momentum_signals": len(outcomes["momentum"]),
        "missing_price": missing_price,
        "embargoed": embargoed,
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
    block_seconds = 4 * WEEK_SECONDS
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


def stratified_permutation_test(
    signals: Sequence[TradeOutcome],
    all_weeks: Sequence[TradeOutcome],
    *,
    cost_bps: float = PRIMARY_COST_BPS,
    replications: int = PLACEBO_REPLICATIONS,
    seed: int = RANDOM_SEED,
) -> dict[str, float | int | None]:
    if not signals or not all_weeks:
        return {"replications": 0, "permuted_mean": None, "empirical_p_value": None}
    pools: dict[tuple[int, int], list[TradeOutcome]] = {}
    counts: dict[tuple[int, int], int] = {}
    for outcome in all_weeks:
        year = datetime.fromtimestamp(outcome.event_timestamp, tz=UTC).year
        pools.setdefault((year, outcome.volatility_decile), []).append(outcome)
    for outcome in signals:
        year = datetime.fromtimestamp(outcome.event_timestamp, tz=UTC).year
        key = (year, outcome.volatility_decile)
        counts[key] = counts.get(key, 0) + 1
    if any(count > len(pools.get(key, ())) for key, count in counts.items()):
        return {"replications": 0, "permuted_mean": None, "empirical_p_value": None}
    observed = statistics.fmean(
        outcome.net_return(cost_bps) for outcome in signals
    )
    rng = random.Random(seed)
    permuted_means: list[float] = []
    for _ in range(replications):
        sampled: list[float] = []
        for key, count in counts.items():
            sampled.extend(
                outcome.net_return(cost_bps)
                for outcome in rng.sample(pools[key], count)
            )
        permuted_means.append(statistics.fmean(sampled))
    exceedances = sum(value >= observed for value in permuted_means)
    return {
        "replications": replications,
        "permuted_mean": statistics.fmean(permuted_means),
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
    by_year = {year: 0.0 for year in required_years}
    by_quarter = {
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
    outcomes: dict[str, list[TradeOutcome]],
    *,
    segment_start: int,
    segment_end: int,
    required_years: Sequence[int],
    data_quality_passed: bool,
) -> dict[str, Any]:
    signals = outcomes["combined"]
    primary = _summary(signals, PRIMARY_COST_BPS)
    stress = _summary(signals, STRESS_COST_BPS)
    binance_only = _summary(outcomes["binance_only"], PRIMARY_COST_BPS)
    kraken_only = _summary(outcomes["kraken_only"], PRIMARY_COST_BPS)
    momentum = _summary(outcomes["momentum"], PRIMARY_COST_BPS)
    always_long = _summary(outcomes["all_weeks"], PRIMARY_COST_BPS)
    lower_bound = block_bootstrap_lower_bound(
        signals, segment_start=segment_start, segment_end=segment_end
    )
    permutation = stratified_permutation_test(signals, outcomes["all_weeks"])
    quarterly = quarterly_robustness(signals, required_years=required_years)
    combined_mean = primary["mean_return"]
    binance_mean = binance_only["mean_return"]
    kraken_mean = kraken_only["mean_return"]
    p_value = permutation["empirical_p_value"]
    signal_timestamps = {outcome.event_timestamp for outcome in signals}
    ordered_weeks = sorted(outcomes["all_weeks"], key=lambda item: item.event_timestamp)
    states = [item.event_timestamp in signal_timestamps for item in ordered_weeks]
    state_changes = sum(left != right for left, right in zip(states, states[1:], strict=False))
    exposure = len(signals) / len(ordered_weeks) if ordered_weeks else 0.0
    calendar_returns = [
        item.net_return(PRIMARY_COST_BPS)
        if item.event_timestamp in signal_timestamps
        else 0.0
        for item in ordered_weeks
    ]
    if len(calendar_returns) >= 2 and statistics.stdev(calendar_returns) > 0:
        annualized_sharpe = (
            statistics.fmean(calendar_returns)
            / statistics.stdev(calendar_returns)
            * math.sqrt(52.0)
        )
    else:
        annualized_sharpe = None
    gates = {
        "min_30_trades": len(signals) >= MIN_TEST_TRADES,
        "eligible_exposure_and_state_changes": len(ordered_weeks) >= 100
        and 0.20 <= exposure <= 0.80
        and state_changes >= 12,
        "positive_pnl": float(primary["pnl_usd"]) > 0,
        "positive_mean": combined_mean is not None and float(combined_mean) > 0,
        "win_rate_50pct": primary["win_rate"] is not None
        and float(primary["win_rate"]) >= 0.50,
        "annualized_weekly_sharpe_0_5": annualized_sharpe is not None
        and annualized_sharpe >= 0.50,
        "bootstrap_lower_bound_positive": lower_bound is not None and lower_bound > 0,
        "beats_permutation_bonferroni": p_value is not None
        and float(p_value) <= FAMILYWISE_P_THRESHOLD,
        "positive_at_100bps": float(stress["pnl_usd"]) > 0,
        "positive_each_year": bool(quarterly["positive_each_year"]),
        "positive_leave_one_quarter_out": bool(
            quarterly["positive_leave_one_quarter_out"]
        ),
        "acceptable_quarter_concentration": bool(
            quarterly["acceptable_quarter_concentration"]
        ),
        "beats_both_single_venue_means": combined_mean is not None
        and binance_mean is not None
        and kraken_mean is not None
        and float(combined_mean) > float(binance_mean)
        and float(combined_mean) > float(kraken_mean),
        "beats_momentum_and_weekly_long_pnl": float(primary["pnl_usd"])
        > float(momentum["pnl_usd"])
        and float(primary["pnl_usd"]) > float(always_long["pnl_usd"]),
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
        "single_venue_baselines": {
            "binance": binance_only,
            "kraken": kraken_only,
            "momentum": momentum,
            "always_long_weekly": always_long,
        },
        "bootstrap_lower_95_one_sided": lower_bound,
        "stratified_permutation": permutation,
        "quarterly_robustness": quarterly,
        "exposure_diagnostics": {
            "eligible_weeks": len(ordered_weeks),
            "exposed_weeks": len(signals),
            "exposure": exposure,
            "state_changes": state_changes,
            "annualized_weekly_sharpe": annualized_sharpe,
        },
        "gates": gates,
    }
