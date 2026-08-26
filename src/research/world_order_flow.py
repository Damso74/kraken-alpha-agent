"""Pure cross-sectional long-only/cash research harness for H-WOF-002."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

WEEK_SECONDS = 7 * 86_400
ENTRY_DELAY_SECONDS = 3_600
PRIMARY_COST_BPS = 100.0
STRESS_COST_BPS = 150.0
MIN_UNIVERSE = 30
MIN_ELIGIBLE_WEEKS = 100
MIN_EXPOSED_WEEKS = 30
MIN_FORWARD_WEEKS = 30
FAMILYWISE_P_THRESHOLD = 0.0166667
BOOTSTRAP_REPLICATIONS = 10_000
RANDOM_SEED = 20_260_826


@dataclass(frozen=True)
class AssetWeek:
    base_asset: str
    week_start: int
    decision_timestamp: int
    flow_imbalance: float
    entry_timestamp: int
    exit_timestamp: int
    entry_price: float
    exit_price: float

    @property
    def gross_return(self) -> float:
        return self.exit_price / self.entry_price - 1.0


@dataclass(frozen=True)
class PortfolioWeek:
    decision_timestamp: int
    entry_timestamp: int
    exit_timestamp: int
    universe_size: int
    target_slots: int
    selected_assets: tuple[str, ...]
    gross_return: float

    def net_return(self, cost_bps: float) -> float:
        exposure_fraction = len(self.selected_assets) / self.target_slots
        return self.gross_return - cost_bps / 10_000.0 * exposure_fraction


def _finite_positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _is_monday_utc(timestamp: int) -> bool:
    moment = datetime.fromtimestamp(timestamp, tz=UTC)
    return moment.weekday() == 0 and moment.hour == 0 and moment.minute == 0 and moment.second == 0


def build_asset_weeks(
    flow_rows: Sequence[Mapping[str, Any]],
    price_rows: Sequence[Mapping[str, Any]],
    universe_by_week: Mapping[int, Sequence[str]],
) -> tuple[list[AssetWeek], dict[str, int]]:
    """Join only complete, causally eligible weekly flow and price rows."""

    flow: dict[tuple[int, str], tuple[float, float]] = {}
    invalid_flow = 0
    for row in flow_rows:
        week = row.get("week_start")
        base = str(row.get("base_asset", "")).upper()
        quote = _finite_positive(row.get("quote_volume"))
        buy = row.get("taker_buy_quote_volume")
        try:
            buy_value = float(buy)
        except (TypeError, ValueError):
            buy_value = math.nan
        if (
            isinstance(week, bool)
            or not isinstance(week, int)
            or not _is_monday_utc(week)
            or not base
            or quote is None
            or not math.isfinite(buy_value)
            or buy_value < 0
            or buy_value > quote
        ):
            invalid_flow += 1
            continue
        key = (week, base)
        value = (2.0 * buy_value - quote, quote)
        if key in flow and flow[key] != value:
            raise ValueError(f"conflicting flow row for {base} at {week}")
        flow[key] = value

    prices: dict[tuple[int, str], tuple[int, int, float, float]] = {}
    invalid_prices = 0
    for row in price_rows:
        week = row.get("week_start")
        base = str(row.get("base_asset", "")).upper()
        entry = _finite_positive(row.get("entry_price"))
        exit_price = _finite_positive(row.get("exit_price"))
        entry_timestamp = row.get("entry_timestamp")
        exit_timestamp = row.get("exit_timestamp")
        if (
            isinstance(week, bool)
            or not isinstance(week, int)
            or not _is_monday_utc(week)
            or not base
            or entry is None
            or exit_price is None
            or not isinstance(entry_timestamp, int)
            or isinstance(entry_timestamp, bool)
            or not isinstance(exit_timestamp, int)
            or isinstance(exit_timestamp, bool)
            or entry_timestamp != week + WEEK_SECONDS + ENTRY_DELAY_SECONDS
            or exit_timestamp != entry_timestamp + WEEK_SECONDS
        ):
            invalid_prices += 1
            continue
        key = (week, base)
        value = (entry_timestamp, exit_timestamp, entry, exit_price)
        if key in prices and prices[key] != value:
            raise ValueError(f"conflicting price row for {base} at {week}")
        prices[key] = value

    output: list[AssetWeek] = []
    missing = 0
    incomplete_weeks = 0
    for week, universe in sorted(universe_by_week.items()):
        if not _is_monday_utc(week):
            raise ValueError("universe week is not a UTC Monday boundary")
        unique_assets = sorted({str(asset).upper() for asset in universe})
        week_rows: list[AssetWeek] = []
        week_missing = 0
        for base in unique_assets:
            flow_value = flow.get((week, base))
            price_value = prices.get((week, base))
            if flow_value is None or price_value is None:
                missing += 1
                week_missing += 1
                continue
            week_rows.append(
                AssetWeek(
                    base_asset=base,
                    week_start=week,
                    decision_timestamp=week + WEEK_SECONDS,
                    flow_imbalance=flow_value[0] / flow_value[1],
                    entry_timestamp=price_value[0],
                    exit_timestamp=price_value[1],
                    entry_price=price_value[2],
                    exit_price=price_value[3],
                )
            )
        if week_missing:
            incomplete_weeks += 1
            continue
        output.extend(week_rows)
    return output, {
        "valid_flow_rows": len(flow),
        "valid_price_rows": len(prices),
        "invalid_flow_rows": invalid_flow,
        "invalid_price_rows": invalid_prices,
        "missing_asset_weeks": missing,
        "incomplete_weeks_excluded": incomplete_weeks,
        "joined_asset_weeks": len(output),
    }


def build_portfolio_weeks(
    asset_weeks: Sequence[AssetWeek],
    *,
    minimum_universe: int = MIN_UNIVERSE,
) -> list[PortfolioWeek]:
    """Select the positive-flow top quintile, equal-weighted; otherwise cash."""

    by_decision: dict[int, list[AssetWeek]] = {}
    for row in asset_weeks:
        by_decision.setdefault(row.decision_timestamp, []).append(row)
    portfolios: list[PortfolioWeek] = []
    for decision, rows in sorted(by_decision.items()):
        unique = {row.base_asset for row in rows}
        if len(unique) != len(rows):
            raise ValueError(f"duplicate asset at decision {decision}")
        if len(rows) < minimum_universe:
            continue
        ranked = sorted(rows, key=lambda row: (-row.flow_imbalance, row.base_asset))
        quintile_size = max(1, math.ceil(len(ranked) / 5))
        selected = [row for row in ranked[:quintile_size] if row.flow_imbalance > 0]
        entry_timestamps = {row.entry_timestamp for row in rows}
        exit_timestamps = {row.exit_timestamp for row in rows}
        if len(entry_timestamps) != 1 or len(exit_timestamps) != 1:
            raise ValueError(f"inconsistent execution timestamps at decision {decision}")
        gross = sum(row.gross_return for row in selected) / quintile_size
        portfolios.append(
            PortfolioWeek(
                decision_timestamp=decision,
                entry_timestamp=next(iter(entry_timestamps)),
                exit_timestamp=next(iter(exit_timestamps)),
                universe_size=len(rows),
                target_slots=quintile_size,
                selected_assets=tuple(sorted(row.base_asset for row in selected)),
                gross_return=gross,
            )
        )
    return portfolios


def _block_bootstrap_lower_bound(
    returns: Sequence[float], *, replications: int = BOOTSTRAP_REPLICATIONS
) -> float | None:
    if len(returns) < 8:
        return None
    rng = random.Random(RANDOM_SEED)
    block_size = 4
    starts = list(range(0, len(returns), block_size))
    estimates: list[float] = []
    for _ in range(replications):
        sample: list[float] = []
        while len(sample) < len(returns):
            start = rng.choice(starts)
            sample.extend(returns[start : start + block_size])
        estimates.append(statistics.fmean(sample[: len(returns)]))
    estimates.sort()
    return estimates[max(0, math.ceil(0.05 * len(estimates)) - 1)]


def _sign_permutation_p_value(
    returns: Sequence[float], *, replications: int = 2_000
) -> float | None:
    exposed = [value for value in returns if value != 0]
    if not exposed:
        return None
    observed = statistics.fmean(exposed)
    rng = random.Random(RANDOM_SEED)
    exceedances = 0
    for _ in range(replications):
        permuted = statistics.fmean(value if rng.random() >= 0.5 else -value for value in exposed)
        if permuted >= observed:
            exceedances += 1
    return (exceedances + 1) / (replications + 1)


def analyze_portfolios(
    portfolios: Sequence[PortfolioWeek],
    *,
    primary_cost_bps: float = PRIMARY_COST_BPS,
    stress_cost_bps: float = STRESS_COST_BPS,
) -> dict[str, Any]:
    ordered = sorted(portfolios, key=lambda row: row.decision_timestamp)
    primary = [row.net_return(primary_cost_bps) for row in ordered]
    stress = [row.net_return(stress_cost_bps) for row in ordered]
    exposed = [row for row in ordered if row.selected_assets]
    yearly: dict[str, float] = {}
    quarterly: dict[str, float] = {}
    for row, value in zip(ordered, primary, strict=True):
        dt = datetime.fromtimestamp(row.decision_timestamp, tz=UTC)
        yearly[str(dt.year)] = yearly.get(str(dt.year), 0.0) + value
        quarter = f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
        quarterly[quarter] = quarterly.get(quarter, 0.0) + value
    lower = _block_bootstrap_lower_bound(primary)
    p_value = _sign_permutation_p_value(primary)
    positive_gains = sum(max(0.0, value) for value in quarterly.values())
    max_concentration = (
        max((max(0.0, value) / positive_gains for value in quarterly.values()), default=0.0)
        if positive_gains > 0
        else 1.0
    )
    leave_one_quarter_out = {quarter: sum(primary) - value for quarter, value in quarterly.items()}
    gates = {
        "eligible_weeks_at_least_100": len(ordered) >= MIN_ELIGIBLE_WEEKS,
        "exposed_weeks_at_least_30": len(exposed) >= MIN_EXPOSED_WEEKS,
        "primary_mean_positive": bool(primary) and statistics.fmean(primary) > 0,
        "stress_mean_positive": bool(stress) and statistics.fmean(stress) > 0,
        "bootstrap_lower_positive": lower is not None and lower > 0,
        "familywise_p_value": p_value is not None and p_value <= FAMILYWISE_P_THRESHOLD,
        "each_year_positive": len(yearly) >= 2 and all(value > 0 for value in yearly.values()),
        "quarter_concentration_at_most_40pct": max_concentration <= 0.40,
        "leave_one_quarter_out_positive": bool(leave_one_quarter_out)
        and all(value > 0 for value in leave_one_quarter_out.values()),
    }
    return {
        "status": "candidate_for_forward_observation" if all(gates.values()) else "no_go",
        "eligible_weeks": len(ordered),
        "exposed_weeks": len(exposed),
        "exposure_rate": len(exposed) / len(ordered) if ordered else 0.0,
        "mean_net_return": statistics.fmean(primary) if primary else None,
        "stress_mean_net_return": statistics.fmean(stress) if stress else None,
        "bootstrap_lower_95_one_sided": lower,
        "permutation_p_value": p_value,
        "yearly_net_returns": yearly,
        "quarterly_net_returns": quarterly,
        "max_positive_quarter_concentration": max_concentration,
        "leave_one_quarter_out": leave_one_quarter_out,
        "gates": gates,
        "portfolio_weeks": [asdict(row) for row in ordered],
    }


def evaluate_forward_outcomes(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    causal_journal_verified: bool,
    cache_reproduction_verified: bool = False,
    ci_verified: bool = False,
) -> dict[str, Any]:
    """Evaluate immutable H-WOF-002 outcomes without reading the network.

    Collection horizon, scientific gates and operational evidence are kept
    separate so an economically attractive sample can never silently bypass
    the frozen 30/100-week requirements, the byte-for-byte cache replay or CI.
    """

    flow_rows: list[Mapping[str, Any]] = []
    price_rows: list[Mapping[str, Any]] = []
    universe_by_week: dict[int, list[str]] = {}
    complete_weeks = 0
    excluded_weeks = 0
    seen_weeks: set[int] = set()
    malformed_outcomes = 0

    for outcome in outcomes:
        status = outcome.get("status")
        rows = outcome.get("rows")
        if not isinstance(rows, list):
            malformed_outcomes += 1
            continue
        if status == "excluded_incomplete_source_week":
            excluded_weeks += 1
            if rows:
                malformed_outcomes += 1
            continue
        if status != "complete" or not rows:
            malformed_outcomes += 1
            continue
        raw_week = rows[0].get("week_start") if isinstance(rows[0], Mapping) else None
        if (
            isinstance(raw_week, bool)
            or not isinstance(raw_week, int)
            or raw_week in seen_weeks
            or any(
                not isinstance(row, Mapping) or row.get("week_start") != raw_week for row in rows
            )
        ):
            malformed_outcomes += 1
            continue
        seen_weeks.add(raw_week)
        complete_weeks += 1
        universe_by_week[raw_week] = [str(row.get("base_asset", "")) for row in rows]
        flow_rows.extend(rows)
        price_rows.extend(rows)

    asset_weeks, join_quality = build_asset_weeks(flow_rows, price_rows, universe_by_week)
    portfolios = build_portfolio_weeks(asset_weeks)
    analysis = analyze_portfolios(portfolios)
    complete_inputs = (
        malformed_outcomes == 0
        and join_quality["invalid_flow_rows"] == 0
        and join_quality["invalid_price_rows"] == 0
        and join_quality["missing_asset_weeks"] == 0
        and join_quality["incomplete_weeks_excluded"] == 0
        and len(portfolios) == complete_weeks
    )
    gates = {
        "causal_journal_verified": bool(causal_journal_verified),
        "complete_week_inputs": complete_inputs,
        "independent_forward_weeks_at_least_30": complete_weeks >= MIN_FORWARD_WEEKS,
        **analysis["gates"],
        "cache_only_reproduction_exact": bool(cache_reproduction_verified),
        "ci_scope_verified": bool(ci_verified),
    }
    scientific_gates = {
        key: value
        for key, value in gates.items()
        if key not in {"cache_only_reproduction_exact", "ci_scope_verified"}
    }
    horizon_ready = (
        complete_weeks >= MIN_FORWARD_WEEKS and analysis["eligible_weeks"] >= MIN_ELIGIBLE_WEEKS
    )
    if not horizon_ready:
        status = "collecting"
    elif not all(scientific_gates.values()):
        status = "no_go"
    elif not all(gates.values()):
        status = "evidence_pending"
    else:
        status = "candidate_for_forward_observation"
    return {
        "schema_version": "hwof002-forward-evaluation-v1",
        "status": status,
        "decision": "REVIEW_REQUIRED" if status == "candidate_for_forward_observation" else "NO-GO",
        "complete_source_weeks": complete_weeks,
        "excluded_source_weeks": excluded_weeks,
        "malformed_outcomes": malformed_outcomes,
        "join_quality": join_quality,
        "analysis": analysis,
        "gates": gates,
        "safety": {
            "authorizes_orders": False,
            "authorizes_paper_or_live": False,
            "human_review_required": True,
        },
    }
