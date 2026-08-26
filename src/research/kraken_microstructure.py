"""Pure research harness for preregistered Kraken microstructure hypothesis H-KM-001."""

from __future__ import annotations

import bisect
import math
import random
import statistics
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .concentration import classify_concentration_risk

HOUR_SECONDS = 3600
SIX_HOURS = 6
HOLD_HOURS = 12
ENTRY_OFFSET_HOURS = 1
EXIT_OFFSET_HOURS = ENTRY_OFFSET_HOURS + HOLD_HOURS
LOOKBACK_HOURS = 180 * 24
MIN_ROLLING_COVERAGE = 0.95
MIN_ROLLING_OBSERVATIONS = math.ceil(LOOKBACK_HOURS * MIN_ROLLING_COVERAGE)
MIN_TEST_TRADES = 30
PRIMARY_COST_BPS = 35.0
STRESS_COST_BPS = 50.0
NOTIONAL_USD = 1000.0
RANDOM_SEED = 20260826
PLACEBO_REPLICATIONS = 2000
BOOTSTRAP_REPLICATIONS = 10000


@dataclass(frozen=True)
class MarketBar:
    timestamp: int
    open: float
    close: float
    open_interest_close: float
    liquidation_volume: float
    aggressor_differential: float


@dataclass(frozen=True)
class FeaturePoint:
    timestamp: int
    price_return_6h: float
    oi_change_6h: float
    liquidation_6h: float
    sell_aggression_6h: float
    volatility_24h: float


@dataclass(frozen=True)
class SignalEvent:
    timestamp: int
    volatility_decile: int
    oi_extreme: bool
    liquidation_extreme: bool
    sell_aggression_extreme: bool


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
        return self.gross_return - float(cost_bps) / 10_000.0


class RollingValues:
    """Timestamped rolling values with deterministic nearest-rank quantiles."""

    def __init__(self) -> None:
        self._queue: deque[tuple[int, float]] = deque()
        self._sorted: list[float] = []

    def evict_before(self, cutoff: int) -> None:
        while self._queue and self._queue[0][0] < cutoff:
            _, value = self._queue.popleft()
            index = bisect.bisect_left(self._sorted, value)
            if index >= len(self._sorted) or self._sorted[index] != value:
                raise RuntimeError("rolling quantile state is inconsistent")
            self._sorted.pop(index)

    def add(self, timestamp: int, value: float) -> None:
        if not math.isfinite(value):
            return
        self._queue.append((int(timestamp), float(value)))
        bisect.insort(self._sorted, float(value))

    def __len__(self) -> int:
        return len(self._sorted)

    def quantile(self, q: float) -> float:
        if not self._sorted:
            raise ValueError("quantile requires at least one value")
        if not 0.0 <= q <= 1.0:
            raise ValueError("q must be between 0 and 1")
        rank = max(1, math.ceil(q * len(self._sorted)))
        return self._sorted[min(rank - 1, len(self._sorted) - 1)]

    def decile(self, value: float) -> int:
        if not self._sorted:
            raise ValueError("decile requires at least one reference value")
        rank = bisect.bisect_right(self._sorted, float(value))
        return min(9, int(rank * 10 / len(self._sorted)))


def _rows_by_timestamp(rows: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    out: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        try:
            ts = int(row["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        out[ts] = row
    return out


def align_market_bars(
    candles: Sequence[Mapping[str, Any]],
    open_interest: Sequence[Mapping[str, Any]],
    liquidations: Sequence[Mapping[str, Any]],
    aggressor: Sequence[Mapping[str, Any]],
) -> tuple[list[MarketBar], dict[str, int]]:
    candle_map = _rows_by_timestamp(candles)
    oi_map = _rows_by_timestamp(open_interest)
    liq_map = _rows_by_timestamp(liquidations)
    aggressor_map = _rows_by_timestamp(aggressor)
    common = sorted(set(candle_map) & set(oi_map) & set(liq_map) & set(aggressor_map))

    bars: list[MarketBar] = []
    invalid = 0
    for ts in common:
        try:
            open_price = float(candle_map[ts]["open"])
            close_price = float(candle_map[ts]["close"])
            oi_close = float(oi_map[ts]["open_interest_close"])
            liq = float(liq_map[ts]["liquidation_volume"])
            aggressive = float(aggressor_map[ts]["aggressor_differential"])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        values = (open_price, close_price, oi_close, liq, aggressive)
        if not all(math.isfinite(value) for value in values):
            invalid += 1
            continue
        if open_price <= 0 or close_price <= 0 or oi_close <= 0 or liq < 0:
            invalid += 1
            continue
        bars.append(
            MarketBar(
                timestamp=ts,
                open=open_price,
                close=close_price,
                open_interest_close=oi_close,
                liquidation_volume=liq,
                aggressor_differential=aggressive,
            )
        )

    quality = {
        "candles": len(candle_map),
        "open_interest": len(oi_map),
        "liquidations": len(liq_map),
        "aggressor": len(aggressor_map),
        "common": len(common),
        "valid": len(bars),
        "invalid": invalid,
    }
    return bars, quality


def build_feature_points(bars: Sequence[MarketBar]) -> list[FeaturePoint]:
    by_timestamp = {bar.timestamp: bar for bar in bars}
    points: list[FeaturePoint] = []
    for ts in sorted(by_timestamp):
        required = [by_timestamp.get(ts - offset * HOUR_SECONDS) for offset in range(25)]
        if any(bar is None for bar in required):
            continue
        dense = [bar for bar in required if bar is not None]
        current = dense[0]
        six_hours_ago = dense[SIX_HOURS]
        price_return = current.close / six_hours_ago.close - 1.0
        oi_change = current.open_interest_close / six_hours_ago.open_interest_close - 1.0
        liquidation = sum(bar.liquidation_volume for bar in dense[:SIX_HOURS])
        aggression = sum(bar.aggressor_differential for bar in dense[:SIX_HOURS])
        hourly_log_returns = [
            math.log(dense[index].close / dense[index + 1].close)
            for index in range(24)
        ]
        volatility = statistics.pstdev(hourly_log_returns)
        points.append(
            FeaturePoint(
                timestamp=ts,
                price_return_6h=price_return,
                oi_change_6h=oi_change,
                liquidation_6h=liquidation,
                sell_aggression_6h=aggression,
                volatility_24h=volatility,
            )
        )
    return points


def generate_signal_events(
    points: Sequence[FeaturePoint],
) -> tuple[list[SignalEvent], list[SignalEvent], dict[str, int]]:
    windows = {
        "price": RollingValues(),
        "oi": RollingValues(),
        "liquidation": RollingValues(),
        "aggression": RollingValues(),
        "volatility": RollingValues(),
    }
    micro_events: list[SignalEvent] = []
    baseline_events: list[SignalEvent] = []
    last_micro = -10**18
    last_baseline = -10**18
    eligible = 0

    for point in sorted(points, key=lambda item: item.timestamp):
        cutoff = point.timestamp - LOOKBACK_HOURS * HOUR_SECONDS
        for window in windows.values():
            window.evict_before(cutoff)

        enough_history = all(
            len(window) >= MIN_ROLLING_OBSERVATIONS for window in windows.values()
        )
        if enough_history:
            eligible += 1
            price_extreme = point.price_return_6h <= windows["price"].quantile(0.10)
            oi_extreme = point.oi_change_6h <= windows["oi"].quantile(0.10)
            liquidation_extreme = point.liquidation_6h >= windows[
                "liquidation"
            ].quantile(0.90)
            aggression_extreme = point.sell_aggression_6h >= windows[
                "aggression"
            ].quantile(0.90)
            decile = windows["volatility"].decile(point.volatility_24h)
            event = SignalEvent(
                timestamp=point.timestamp,
                volatility_decile=decile,
                oi_extreme=oi_extreme,
                liquidation_extreme=liquidation_extreme,
                sell_aggression_extreme=aggression_extreme,
            )
            if (
                price_extreme
                and point.timestamp - last_baseline >= HOLD_HOURS * HOUR_SECONDS
            ):
                baseline_events.append(event)
                last_baseline = point.timestamp
            condition_count = sum((oi_extreme, liquidation_extreme, aggression_extreme))
            if (
                price_extreme
                and condition_count >= 2
                and point.timestamp - last_micro >= HOLD_HOURS * HOUR_SECONDS
            ):
                micro_events.append(event)
                last_micro = point.timestamp

        windows["price"].add(point.timestamp, point.price_return_6h)
        windows["oi"].add(point.timestamp, point.oi_change_6h)
        windows["liquidation"].add(point.timestamp, point.liquidation_6h)
        windows["aggression"].add(point.timestamp, point.sell_aggression_6h)
        windows["volatility"].add(point.timestamp, point.volatility_24h)

    diagnostics = {
        "feature_points": len(points),
        "eligible_points": eligible,
        "micro_events": len(micro_events),
        "baseline_events": len(baseline_events),
    }
    return micro_events, baseline_events, diagnostics


def build_trade_outcomes(
    events: Sequence[SignalEvent],
    bars: Sequence[MarketBar],
    *,
    segment_start: int,
    segment_end: int,
) -> list[TradeOutcome]:
    by_timestamp = {bar.timestamp: bar for bar in bars}
    outcomes: list[TradeOutcome] = []
    for event in events:
        if not segment_start <= event.timestamp < segment_end:
            continue
        entry_ts = event.timestamp + ENTRY_OFFSET_HOURS * HOUR_SECONDS
        exit_ts = event.timestamp + EXIT_OFFSET_HOURS * HOUR_SECONDS
        if exit_ts >= segment_end:
            continue
        entry = by_timestamp.get(entry_ts)
        exit_bar = by_timestamp.get(exit_ts)
        if entry is None or exit_bar is None or entry.open <= 0 or exit_bar.open <= 0:
            continue
        outcomes.append(
            TradeOutcome(
                event_timestamp=event.timestamp,
                entry_timestamp=entry_ts,
                exit_timestamp=exit_ts,
                volatility_decile=event.volatility_decile,
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
        "pnl_usd": sum(value * NOTIONAL_USD for value in returns),
        "best_return": max(returns),
        "worst_return": min(returns),
    }


def _calendar_week(timestamp: int) -> tuple[int, int]:
    dt = datetime.fromtimestamp(timestamp, tz=UTC)
    year, week, _ = dt.isocalendar()
    return year, week


def block_bootstrap_lower_bound(
    outcomes: Sequence[TradeOutcome],
    *,
    cost_bps: float = PRIMARY_COST_BPS,
    replications: int = BOOTSTRAP_REPLICATIONS,
    seed: int = RANDOM_SEED,
) -> float | None:
    if not outcomes:
        return None
    by_week: dict[tuple[int, int], list[float]] = {}
    for outcome in outcomes:
        by_week.setdefault(_calendar_week(outcome.event_timestamp), []).append(
            outcome.net_return(cost_bps)
        )
    blocks = list(by_week.values())
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(replications):
        sampled: list[float] = []
        for _block in blocks:
            sampled.extend(rng.choice(blocks))
        means.append(statistics.fmean(sampled))
    means.sort()
    return means[max(0, math.floor(0.05 * (len(means) - 1)))]


def matched_baseline_test(
    micro: Sequence[TradeOutcome],
    baseline: Sequence[TradeOutcome],
    *,
    cost_bps: float = PRIMARY_COST_BPS,
    replications: int = PLACEBO_REPLICATIONS,
    seed: int = RANDOM_SEED,
) -> dict[str, float | int | None]:
    if not micro or not baseline:
        return {
            "replications": 0,
            "matched_mean": None,
            "empirical_p_value": None,
        }
    pools: dict[tuple[int, int], list[TradeOutcome]] = {}
    by_year: dict[int, list[TradeOutcome]] = {}
    for outcome in baseline:
        year = datetime.fromtimestamp(outcome.event_timestamp, tz=UTC).year
        pools.setdefault((year, outcome.volatility_decile), []).append(outcome)
        by_year.setdefault(year, []).append(outcome)
    rng = random.Random(seed)
    observed = statistics.fmean(outcome.net_return(cost_bps) for outcome in micro)
    placebo_means: list[float] = []
    for _ in range(replications):
        sampled: list[float] = []
        for outcome in micro:
            year = datetime.fromtimestamp(outcome.event_timestamp, tz=UTC).year
            pool = pools.get((year, outcome.volatility_decile)) or by_year.get(year)
            if not pool:
                pool = list(baseline)
            sampled.append(rng.choice(pool).net_return(cost_bps))
        placebo_means.append(statistics.fmean(sampled))
    exceedances = sum(value >= observed for value in placebo_means)
    return {
        "replications": replications,
        "matched_mean": statistics.fmean(placebo_means),
        "empirical_p_value": (exceedances + 1) / (replications + 1),
    }


def jackknife_robustness(
    outcomes: Sequence[TradeOutcome], cost_bps: float = PRIMARY_COST_BPS
) -> dict[str, Any]:
    returns = [outcome.net_return(cost_bps) for outcome in outcomes]
    if len(returns) < 2:
        return {"passed": False, "reason": "fewer than two trades"}
    mean = statistics.fmean(returns)
    largest_index = max(range(len(returns)), key=lambda index: abs(returns[index]))
    reduced = [value for index, value in enumerate(returns) if index != largest_index]
    reduced_mean = statistics.fmean(reduced)
    drop = abs(mean - reduced_mean) / abs(mean) if abs(mean) > 1e-15 else math.inf
    hit_rate = sum(value > 0 for value in reduced) / len(reduced)
    passed = reduced_mean > 0 and drop <= 0.50 and hit_rate >= 0.50
    return {
        "passed": passed,
        "removed_index": largest_index,
        "removed_return": returns[largest_index],
        "mean_without_largest": reduced_mean,
        "mean_change_fraction": drop,
        "hit_rate_without_largest": hit_rate,
    }


def analyze_segment(
    micro: Sequence[TradeOutcome],
    baseline: Sequence[TradeOutcome],
    *,
    segment_start: int,
    segment_end: int,
    eligible_bar_count: int,
    data_quality_passed: bool,
) -> dict[str, Any]:
    primary = _summary(micro, PRIMARY_COST_BPS)
    stress = {
        str(cost): _summary(micro, cost)
        for cost in (20.0, PRIMARY_COST_BPS, STRESS_COST_BPS, 100.0)
    }
    baseline_summary = _summary(baseline, PRIMARY_COST_BPS)
    lower_bound = block_bootstrap_lower_bound(micro)
    matched = matched_baseline_test(micro, baseline)
    contributions = [outcome.net_return(PRIMARY_COST_BPS) for outcome in micro]
    concentration = classify_concentration_risk(
        contributions,
        event_timestamps=[outcome.event_timestamp for outcome in micro],
        min_events=MIN_TEST_TRADES,
    )
    robustness = jackknife_robustness(micro)
    days = max(1.0, (segment_end - segment_start) / 86400.0)
    rotations_per_day = len(micro) / days
    event_rate = len(micro) / max(1, eligible_bar_count)
    matched_mean = matched["matched_mean"]
    empirical_p = matched["empirical_p_value"]

    gates = {
        "min_30_trades": len(micro) >= MIN_TEST_TRADES,
        "positive_pnl": float(primary["pnl_usd"]) > 0,
        "positive_mean": primary["mean_return"] is not None
        and float(primary["mean_return"]) > 0,
        "win_rate_50pct": primary["win_rate"] is not None
        and float(primary["win_rate"]) >= 0.50,
        "bootstrap_lower_bound_positive": lower_bound is not None and lower_bound > 0,
        "beats_matched_price_baseline": primary["mean_return"] is not None
        and matched_mean is not None
        and float(primary["mean_return"]) > float(matched_mean)
        and empirical_p is not None
        and float(empirical_p) <= 0.05,
        "positive_at_50bps": float(stress[str(STRESS_COST_BPS)]["pnl_usd"]) > 0,
        "jackknife_robust": bool(robustness.get("passed")),
        "acceptable_concentration": concentration.verdict == "acceptable",
        "turnover_and_event_rate": rotations_per_day <= 1.0 and event_rate <= 0.30,
        "data_quality": bool(data_quality_passed),
    }
    passed = all(gates.values())
    if len(micro) < MIN_TEST_TRADES:
        status = "insufficient_power"
    else:
        status = "pass" if passed else "not_supported"
    return {
        "status": status,
        "passed": passed,
        "primary_cost_bps": PRIMARY_COST_BPS,
        "microstructure": primary,
        "price_only_baseline": baseline_summary,
        "stress_costs": stress,
        "bootstrap_lower_95_one_sided": lower_bound,
        "matched_baseline": matched,
        "jackknife": robustness,
        "concentration": asdict(concentration),
        "rotations_per_day": rotations_per_day,
        "event_rate": event_rate,
        "gates": gates,
    }


__all__ = [
    "MarketBar",
    "FeaturePoint",
    "SignalEvent",
    "TradeOutcome",
    "RollingValues",
    "align_market_bars",
    "build_feature_points",
    "generate_signal_events",
    "build_trade_outcomes",
    "block_bootstrap_lower_bound",
    "matched_baseline_test",
    "jackknife_robustness",
    "analyze_segment",
]
