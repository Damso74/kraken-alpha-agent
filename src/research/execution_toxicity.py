"""Forward-only shadow metrics for preregistered hypothesis H-EXE-001.

The engine consumes normalized public L2/trade events and evaluates fictive
execution choices.  It deliberately exposes no order adapter and cannot send an
order.  Passive fills use a pessimistic displayed-queue multiplier; unfilled
orders are forced across at the horizon with an additional penalty.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

Side = Literal["buy", "sell"]
Route = Literal["cross", "passive"]

PRESSURE_WINDOW_MS = 5_000
MAX_BOOK_AGE_MS = 1_000
SWEEP_MIN_RATIO = 1.0
TOXICITY_ROUTE_THRESHOLD = 2.0
EVENT_COOLDOWN_MS = 1_000
MARKOUT_HORIZONS_MS = (5_000, 30_000, 60_000)
EXECUTION_HORIZON_MS = 60_000
QUEUE_AHEAD_MULTIPLIER = 2.0
TAKER_FEE_BPS = 5.0
MAKER_FEE_BPS = 2.0
TAKER_SLIPPAGE_BPS = 5.0
NONCOMPLETION_PENALTY_BPS = 5.0
STRESS_PENALTY_BPS = 5.0
MIN_FORWARD_DAYS = 30
MIN_COMPLETED_PROBES = 10_000
MIN_COMPLETION_RATE = 0.95
MIN_SAVINGS_BPS = 5.0
BOOTSTRAP_REPLICATIONS = 10_000
RANDOM_SEED = 20260826


@dataclass(frozen=True)
class BookTick:
    product_id: str
    exchange_timestamp_ms: int
    received_wall_ns: int
    bid: float
    bid_qty: float
    ask: float
    ask_qty: float
    mid: float
    imbalance: float
    observed_transport_lag_ms: float


@dataclass
class PendingProbe:
    probe_id: str
    product_id: str
    side: Side
    route: Route
    decision_timestamp_ms: int
    decision_mid: float
    decision_bid: float
    decision_ask: float
    decision_transport_lag_ms: float
    sweep_ratio: float
    aligned_pressure: float
    aligned_imbalance: float
    toxicity_score: float
    passive_price: float
    queue_ahead_qty: float
    baseline_execution_price: float
    passive_traded_qty: float = 0.0
    passive_fill_timestamp_ms: int | None = None
    router_execution_price: float | None = None
    markouts_bps: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletedProbe:
    probe_id: str
    product_id: str
    side: Side
    route: Route
    decision_timestamp_ms: int
    completion_timestamp_ms: int
    decision_transport_lag_ms: float
    sweep_ratio: float
    aligned_pressure: float
    aligned_imbalance: float
    toxicity_score: float
    queue_ahead_qty: float
    passive_traded_qty: float
    passive_filled: bool
    completed_within_horizon: bool
    baseline_implementation_shortfall_bps: float
    router_implementation_shortfall_bps: float
    savings_bps: float
    stress_savings_bps: float
    markout_5s_bps: float
    markout_30s_bps: float
    markout_60s_bps: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _side_sign(side: Side) -> float:
    return 1.0 if side == "buy" else -1.0


def _implementation_shortfall_bps(
    *, side: Side, decision_mid: float, execution_price: float, costs_bps: float
) -> float:
    return _side_sign(side) * (execution_price / decision_mid - 1.0) * 10_000.0 + costs_bps


def _book_tick(event: Mapping[str, Any]) -> BookTick:
    required = (
        "product_id",
        "exchange_timestamp_ms",
        "received_wall_ns",
        "bid",
        "bid_qty",
        "ask",
        "ask_qty",
        "mid",
        "imbalance",
        "observed_transport_lag_ms",
    )
    if any(key not in event for key in required):
        raise ValueError("book event is missing H-EXE-001 fields")
    tick = BookTick(
        product_id=str(event["product_id"]),
        exchange_timestamp_ms=int(event["exchange_timestamp_ms"]),
        received_wall_ns=int(event["received_wall_ns"]),
        bid=float(event["bid"]),
        bid_qty=float(event["bid_qty"]),
        ask=float(event["ask"]),
        ask_qty=float(event["ask_qty"]),
        mid=float(event["mid"]),
        imbalance=float(event["imbalance"]),
        observed_transport_lag_ms=float(event["observed_transport_lag_ms"]),
    )
    values = (tick.bid, tick.bid_qty, tick.ask, tick.ask_qty, tick.mid)
    if not all(math.isfinite(value) and value > 0 for value in values) or tick.bid >= tick.ask:
        raise ValueError("invalid top-of-book event")
    return tick


class ExecutionToxicityShadow:
    """Deterministic online shadow engine for one Kraken perpetual product."""

    def __init__(self, product_id: str) -> None:
        self.product_id = product_id
        self.latest_book: BookTick | None = None
        self._recent_trades: deque[tuple[int, float, float]] = deque()
        self._pending: list[PendingProbe] = []
        self.completed: list[CompletedProbe] = []
        self._last_probe_ms = -10**18
        self._counter = 0
        self.book_events = 0
        self.trade_events = 0
        self.connection_resets = 0
        self.discarded_pending_on_reset = 0

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def reset_connection(self) -> None:
        """Discard probes that would otherwise span an unobserved network gap."""
        self.connection_resets += 1
        self.discarded_pending_on_reset += len(self._pending)
        self.latest_book = None
        self._recent_trades.clear()
        self._pending.clear()
        self._last_probe_ms = -10**18

    def process_event(self, event: Mapping[str, Any]) -> list[CompletedProbe]:
        if str(event.get("product_id")) != self.product_id:
            raise ValueError("event product does not match shadow engine")
        event_type = str(event.get("event_type", ""))
        if event_type in {"book_snapshot", "book_delta"}:
            return self._on_book(_book_tick(event))
        if event_type == "trade":
            self._on_trade(event)
            return []
        raise ValueError(f"unsupported H-EXE-001 event_type: {event_type!r}")

    def _on_book(self, tick: BookTick) -> list[CompletedProbe]:
        if self.latest_book is not None and tick.exchange_timestamp_ms < self.latest_book.exchange_timestamp_ms:
            raise ValueError("book timestamp moved backwards")
        self.latest_book = tick
        self.book_events += 1
        newly_completed: list[CompletedProbe] = []
        still_pending: list[PendingProbe] = []
        for probe in self._pending:
            elapsed = tick.exchange_timestamp_ms - probe.decision_timestamp_ms
            sign = _side_sign(probe.side)
            for horizon in MARKOUT_HORIZONS_MS:
                if elapsed >= horizon and horizon not in probe.markouts_bps:
                    probe.markouts_bps[horizon] = sign * (
                        tick.mid / probe.decision_mid - 1.0
                    ) * 10_000.0
            if elapsed >= EXECUTION_HORIZON_MS:
                completed = self._complete_probe(probe, tick)
                self.completed.append(completed)
                newly_completed.append(completed)
            else:
                still_pending.append(probe)
        self._pending = still_pending
        return newly_completed

    def _on_trade(self, event: Mapping[str, Any]) -> None:
        if bool(event.get("snapshot")):
            return
        self.trade_events += 1
        timestamp_ms = int(event["exchange_timestamp_ms"])
        side = str(event.get("side"))
        if side not in {"buy", "sell"}:
            raise ValueError("invalid trade side")
        typed_side: Side = "buy" if side == "buy" else "sell"
        price = float(event["price"])
        qty = float(event["qty"])
        if not math.isfinite(price) or not math.isfinite(qty) or price <= 0 or qty <= 0:
            raise ValueError("invalid trade price or quantity")

        self._update_passive_fills(typed_side, price, qty, timestamp_ms)
        signed_qty = qty * _side_sign(typed_side)
        self._recent_trades.append((timestamp_ms, signed_qty, qty))
        cutoff = timestamp_ms - PRESSURE_WINDOW_MS
        while self._recent_trades and self._recent_trades[0][0] < cutoff:
            self._recent_trades.popleft()

        book = self.latest_book
        if book is None:
            return
        book_age_ms = timestamp_ms - book.exchange_timestamp_ms
        if book_age_ms <= 0 or book_age_ms > MAX_BOOK_AGE_MS:
            return
        opposite_top_qty = book.ask_qty if typed_side == "buy" else book.bid_qty
        sweep_ratio = qty / opposite_top_qty
        if sweep_ratio < SWEEP_MIN_RATIO or timestamp_ms - self._last_probe_ms < EVENT_COOLDOWN_MS:
            return
        total_qty = sum(item[2] for item in self._recent_trades)
        raw_pressure = sum(item[1] for item in self._recent_trades) / total_qty if total_qty else 0.0
        sign = _side_sign(typed_side)
        aligned_pressure = sign * raw_pressure
        aligned_imbalance = sign * book.imbalance
        score = sweep_ratio + max(0.0, aligned_pressure) + max(0.0, aligned_imbalance)
        route: Route = "cross" if score >= TOXICITY_ROUTE_THRESHOLD else "passive"
        passive_price = book.bid if typed_side == "buy" else book.ask
        queue_ahead = book.bid_qty if typed_side == "buy" else book.ask_qty
        baseline_price = book.ask if typed_side == "buy" else book.bid
        router_price = baseline_price if route == "cross" else None
        self._counter += 1
        self._pending.append(
            PendingProbe(
                probe_id=f"{self.product_id}-{timestamp_ms}-{self._counter}",
                product_id=self.product_id,
                side=typed_side,
                route=route,
                decision_timestamp_ms=timestamp_ms,
                decision_mid=book.mid,
                decision_bid=book.bid,
                decision_ask=book.ask,
                decision_transport_lag_ms=float(event.get("observed_transport_lag_ms", 0.0)),
                sweep_ratio=sweep_ratio,
                aligned_pressure=aligned_pressure,
                aligned_imbalance=aligned_imbalance,
                toxicity_score=score,
                passive_price=passive_price,
                queue_ahead_qty=queue_ahead,
                baseline_execution_price=baseline_price,
                router_execution_price=router_price,
            )
        )
        self._last_probe_ms = timestamp_ms

    def _update_passive_fills(
        self, taker_side: Side, trade_price: float, qty: float, timestamp_ms: int
    ) -> None:
        for probe in self._pending:
            if probe.route != "passive" or probe.passive_fill_timestamp_ms is not None:
                continue
            if timestamp_ms < probe.decision_timestamp_ms:
                continue
            eligible = (
                probe.side == "buy" and taker_side == "sell" and trade_price <= probe.passive_price
            ) or (
                probe.side == "sell" and taker_side == "buy" and trade_price >= probe.passive_price
            )
            if not eligible:
                continue
            probe.passive_traded_qty += qty
            required = QUEUE_AHEAD_MULTIPLIER * probe.queue_ahead_qty
            if probe.passive_traded_qty >= required:
                probe.passive_fill_timestamp_ms = timestamp_ms
                probe.router_execution_price = probe.passive_price

    def _complete_probe(self, probe: PendingProbe, tick: BookTick) -> CompletedProbe:
        baseline_is = _implementation_shortfall_bps(
            side=probe.side,
            decision_mid=probe.decision_mid,
            execution_price=probe.baseline_execution_price,
            costs_bps=TAKER_FEE_BPS + TAKER_SLIPPAGE_BPS,
        )
        passive_filled = probe.passive_fill_timestamp_ms is not None
        if probe.route == "cross":
            router_price = probe.baseline_execution_price
            router_costs = TAKER_FEE_BPS + TAKER_SLIPPAGE_BPS
            completed_within = True
        elif passive_filled:
            assert probe.router_execution_price is not None
            router_price = probe.router_execution_price
            router_costs = MAKER_FEE_BPS
            completed_within = True
        else:
            router_price = tick.ask if probe.side == "buy" else tick.bid
            router_costs = TAKER_FEE_BPS + TAKER_SLIPPAGE_BPS + NONCOMPLETION_PENALTY_BPS
            completed_within = False
        router_is = _implementation_shortfall_bps(
            side=probe.side,
            decision_mid=probe.decision_mid,
            execution_price=router_price,
            costs_bps=router_costs,
        )
        savings = baseline_is - router_is
        missing_markouts = set(MARKOUT_HORIZONS_MS) - set(probe.markouts_bps)
        if missing_markouts:
            raise RuntimeError(f"probe is missing markouts: {sorted(missing_markouts)}")
        return CompletedProbe(
            probe_id=probe.probe_id,
            product_id=probe.product_id,
            side=probe.side,
            route=probe.route,
            decision_timestamp_ms=probe.decision_timestamp_ms,
            completion_timestamp_ms=tick.exchange_timestamp_ms,
            decision_transport_lag_ms=probe.decision_transport_lag_ms,
            sweep_ratio=probe.sweep_ratio,
            aligned_pressure=probe.aligned_pressure,
            aligned_imbalance=probe.aligned_imbalance,
            toxicity_score=probe.toxicity_score,
            queue_ahead_qty=probe.queue_ahead_qty,
            passive_traded_qty=probe.passive_traded_qty,
            passive_filled=passive_filled,
            completed_within_horizon=completed_within,
            baseline_implementation_shortfall_bps=baseline_is,
            router_implementation_shortfall_bps=router_is,
            savings_bps=savings,
            stress_savings_bps=savings - STRESS_PENALTY_BPS,
            markout_5s_bps=probe.markouts_bps[5_000],
            markout_30s_bps=probe.markouts_bps[30_000],
            markout_60s_bps=probe.markouts_bps[60_000],
        )


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def daily_block_bootstrap_lower_bound(
    observations: Sequence[CompletedProbe],
    *,
    replications: int = BOOTSTRAP_REPLICATIONS,
    seed: int = RANDOM_SEED,
) -> float | None:
    if not observations:
        return None
    by_day: dict[str, list[float]] = {}
    for item in observations:
        day = datetime.fromtimestamp(
            item.decision_timestamp_ms / 1000.0, tz=UTC
        ).date().isoformat()
        by_day.setdefault(day, []).append(item.savings_bps)
    blocks = list(by_day.values())
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(replications):
        sample: list[float] = []
        for _block in blocks:
            sample.extend(rng.choice(blocks))
        means.append(statistics.fmean(sample))
    return _percentile(means, 0.05)


def summarize_shadow_observations(
    observations: Sequence[CompletedProbe],
) -> dict[str, Any]:
    if not observations:
        return {
            "schema_version": "h-exe-001-v1",
            "status": "insufficient_power",
            "decision": "NO-GO",
            "completed_probes": 0,
            "gates": {"passed": False, "reason_codes": ["NO_COMPLETED_PROBES"]},
        }
    savings = [item.savings_bps for item in observations]
    stress = [item.stress_savings_bps for item in observations]
    dates = {
        datetime.fromtimestamp(item.decision_timestamp_ms / 1000.0, tz=UTC).date()
        for item in observations
    }
    completion_rate = sum(item.completed_within_horizon for item in observations) / len(
        observations
    )
    per_product_mean = {
        product: statistics.fmean(item.savings_bps for item in observations if item.product_id == product)
        for product in sorted({item.product_id for item in observations})
    }
    bootstrap_lower = daily_block_bootstrap_lower_bound(observations)
    mean_savings = statistics.fmean(savings)
    mean_stress = statistics.fmean(stress)
    reasons: list[str] = []
    if len(observations) < MIN_COMPLETED_PROBES:
        reasons.append("MIN_COMPLETED_PROBES")
    if len(dates) < MIN_FORWARD_DAYS:
        reasons.append("MIN_FORWARD_DAYS")
    if mean_savings < MIN_SAVINGS_BPS:
        reasons.append("MEAN_SAVINGS_BELOW_5_BPS")
    if mean_stress < MIN_SAVINGS_BPS:
        reasons.append("STRESS_SAVINGS_BELOW_5_BPS")
    if bootstrap_lower is None or bootstrap_lower <= 0:
        reasons.append("BOOTSTRAP_LOWER_NOT_POSITIVE")
    if completion_rate < MIN_COMPLETION_RATE:
        reasons.append("COMPLETION_RATE_BELOW_95_PERCENT")
    if len(per_product_mean) < 2:
        reasons.append("REPLICATION_REQUIRES_TWO_PRODUCTS")
    elif any(value <= 0 for value in per_product_mean.values()):
        reasons.append("PRODUCT_REPLICATION_NOT_POSITIVE")
    passed = not reasons
    p99_lag = _percentile(
        [item.decision_transport_lag_ms for item in observations], 0.99
    )
    return {
        "schema_version": "h-exe-001-v1",
        "status": "candidate_for_forward_observation" if passed else "insufficient_power",
        "decision": "REVIEW_REQUIRED" if passed else "NO-GO",
        "completed_probes": len(observations),
        "distinct_utc_days": len(dates),
        "route_counts": {
            "cross": sum(item.route == "cross" for item in observations),
            "passive": sum(item.route == "passive" for item in observations),
        },
        "mean_savings_bps_by_product": per_product_mean,
        "passive_fills": sum(item.passive_filled for item in observations),
        "completion_within_horizon_rate": completion_rate,
        "mean_savings_bps": mean_savings,
        "median_savings_bps": statistics.median(savings),
        "mean_stress_savings_bps": mean_stress,
        "bootstrap_daily_lower_95_bps": bootstrap_lower,
        "observed_transport_lag_p99_ms": p99_lag,
        "mean_markout_bps": {
            "5s": statistics.fmean(item.markout_5s_bps for item in observations),
            "30s": statistics.fmean(item.markout_30s_bps for item in observations),
            "60s": statistics.fmean(item.markout_60s_bps for item in observations),
        },
        "gates": {"passed": passed, "reason_codes": reasons or ["ALL_GATES_PASSED"]},
        "safety": {
            "shadow_only": True,
            "orders_sent": 0,
            "private_credentials_used": False,
            "human_review_required": True,
        },
    }
