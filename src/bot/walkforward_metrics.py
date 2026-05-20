"""Walk-forward stability metrics and verdict classification."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

WalkForwardVerdict = Literal[
    "blocked_data",
    "insufficient_candles",
    "failed_walkforward",
    "unstable",
    "weak",
    "validation_candidate",
    "paper_candidate_walkforward",
]

MIN_WINDOWS_FOR_VERDICT = 3
MIN_POSITIVE_WINDOW_RATE = 0.60
MIN_HOLDOUT_PASS_RATE = 0.50
MAX_WORST_WINDOW_DRAWDOWN_PCT = 25.0
MAX_MEDIAN_COST_DRAG_PCT = 40.0
MIN_MEDIAN_NET_RETURN_PCT = 0.0
HOLDOUT_PASS_MIN_RETURN_PCT = -5.0
HOLDOUT_PASS_MAX_DRAWDOWN_PCT = 20.0


@dataclass
class WindowRunMetrics:
    window_id: int
    period: str
    net_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    trade_count: int = 0
    cost_drag_pct: float = 0.0
    sharpe_ratio: float = 0.0
    passed: bool = False


@dataclass
class WalkForwardAggregate:
    windows_total: int = 0
    windows_passed: int = 0
    windows_failed: int = 0
    median_net_return: float = 0.0
    mean_net_return: float = 0.0
    worst_window_return: float = 0.0
    max_window_drawdown: float = 0.0
    positive_window_rate: float = 0.0
    consistency_score: float = 0.0
    parameter_stability: float = 1.0
    turnover_stability: float = 0.0
    cost_drag_stability: float = 0.0
    holdout_pass_rate: float = 0.0
    holdout_returns: list[float] = field(default_factory=list)


@dataclass
class WalkForwardVerdictResult:
    verdict: WalkForwardVerdict
    reasons: list[str] = field(default_factory=list)
    aggregate: WalkForwardAggregate | None = None


def _holdout_passes(m: WindowRunMetrics) -> bool:
    return (
        m.net_return_pct >= HOLDOUT_PASS_MIN_RETURN_PCT
        and m.max_drawdown_pct <= HOLDOUT_PASS_MAX_DRAWDOWN_PCT
        and m.trade_count >= 1
    )


def aggregate_window_metrics(
    holdout_runs: Sequence[WindowRunMetrics],
    validation_runs: Sequence[WindowRunMetrics] | None = None,
) -> WalkForwardAggregate:
    """Compute stability aggregates from per-window holdout runs."""
    agg = WalkForwardAggregate()
    if not holdout_runs:
        return agg

    returns = [r.net_return_pct for r in holdout_runs]
    drawdowns = [r.max_drawdown_pct for r in holdout_runs]
    trades = [float(r.trade_count) for r in holdout_runs]
    costs = [r.cost_drag_pct for r in holdout_runs]

    agg.windows_total = len(holdout_runs)
    agg.holdout_returns = list(returns)
    agg.windows_passed = sum(1 for r in holdout_runs if _holdout_passes(r))
    agg.windows_failed = agg.windows_total - agg.windows_passed
    agg.median_net_return = statistics.median(returns)
    agg.mean_net_return = statistics.mean(returns)
    agg.worst_window_return = min(returns)
    agg.max_window_drawdown = max(drawdowns) if drawdowns else 0.0
    agg.positive_window_rate = sum(1 for x in returns if x > 0) / len(returns)
    agg.holdout_pass_rate = agg.windows_passed / agg.windows_total

    if len(returns) >= 2:
        stdev = statistics.pstdev(returns)
        agg.consistency_score = max(0.0, 1.0 - stdev / (abs(agg.mean_net_return) + 1.0))
    else:
        agg.consistency_score = 0.0

    if len(trades) >= 2 and statistics.mean(trades) > 0:
        trade_stdev = statistics.pstdev(trades)
        agg.turnover_stability = max(0.0, 1.0 - trade_stdev / statistics.mean(trades))
    else:
        agg.turnover_stability = 0.0

    if len(costs) >= 2:
        cost_stdev = statistics.pstdev(costs)
        agg.cost_drag_stability = max(0.0, 1.0 - cost_stdev / (statistics.mean(costs) + 1.0))
    else:
        agg.cost_drag_stability = 0.0

    if validation_runs:
        val_returns = [r.net_return_pct for r in validation_runs]
        if len(val_returns) >= 2 and len(returns) >= 2:
            # parameter_stability proxy: correlation sign agreement val vs holdout
            same_sign = sum(
                1
                for v, h in zip(val_returns, returns, strict=False)
                if (v >= 0) == (h >= 0)
            )
            agg.parameter_stability = same_sign / min(len(val_returns), len(returns))

    return agg


def classify_walkforward_verdict(
    agg: WalkForwardAggregate,
    context: Mapping[str, Any] | None = None,
) -> WalkForwardVerdictResult:
    """Classify walk-forward stability; never emits micro_live_candidate."""
    ctx = dict(context or {})
    if not ctx.get("data_ok", True):
        return WalkForwardVerdictResult(
            "blocked_data",
            [str(ctx.get("blocked_reason", "missing cache"))],
        )
    if ctx.get("plan_status") == "insufficient_candles":
        return WalkForwardVerdictResult(
            "insufficient_candles",
            [str(ctx.get("blocked_reason", "insufficient candles for windows"))],
        )
    if agg.windows_total < MIN_WINDOWS_FOR_VERDICT:
        return WalkForwardVerdictResult(
            "failed_walkforward",
            [f"windows_total={agg.windows_total} < {MIN_WINDOWS_FOR_VERDICT}"],
            aggregate=agg,
        )

    reasons: list[str] = []

    if agg.holdout_pass_rate < MIN_HOLDOUT_PASS_RATE:
        reasons.append(f"holdout_pass_rate={agg.holdout_pass_rate:.2%}")

    if agg.positive_window_rate < MIN_POSITIVE_WINDOW_RATE:
        reasons.append(f"positive_window_rate={agg.positive_window_rate:.2%}")

    if agg.median_net_return <= MIN_MEDIAN_NET_RETURN_PCT:
        reasons.append(f"median_net_return={agg.median_net_return:.2f}%")

    if agg.max_window_drawdown > MAX_WORST_WINDOW_DRAWDOWN_PCT:
        reasons.append(f"max_window_drawdown={agg.max_window_drawdown:.2f}%")

    if agg.cost_drag_stability < 0.3 and agg.windows_total >= MIN_WINDOWS_FOR_VERDICT:
        reasons.append(f"cost_drag_unstable={agg.cost_drag_stability:.2f}")

    if reasons:
        if agg.positive_window_rate >= 0.40 and agg.median_net_return > -5.0:
            return WalkForwardVerdictResult("unstable", reasons, aggregate=agg)
        if agg.median_net_return > -10.0:
            return WalkForwardVerdictResult("weak", reasons, aggregate=agg)
        return WalkForwardVerdictResult("failed_walkforward", reasons, aggregate=agg)

    if agg.consistency_score < 0.35:
        return WalkForwardVerdictResult(
            "validation_candidate",
            [f"consistency_score={agg.consistency_score:.2f}"],
            aggregate=agg,
        )

    return WalkForwardVerdictResult(
        "paper_candidate_walkforward",
        ["meets walk-forward stability thresholds"],
        aggregate=agg,
    )


def aggregate_to_dict(agg: WalkForwardAggregate) -> dict[str, Any]:
    return {
        "windows_total": agg.windows_total,
        "windows_passed": agg.windows_passed,
        "windows_failed": agg.windows_failed,
        "median_net_return": round(agg.median_net_return, 4),
        "mean_net_return": round(agg.mean_net_return, 4),
        "worst_window_return": round(agg.worst_window_return, 4),
        "max_window_drawdown": round(agg.max_window_drawdown, 4),
        "positive_window_rate": round(agg.positive_window_rate, 4),
        "consistency_score": round(agg.consistency_score, 4),
        "parameter_stability": round(agg.parameter_stability, 4),
        "turnover_stability": round(agg.turnover_stability, 4),
        "cost_drag_stability": round(agg.cost_drag_stability, 4),
        "holdout_pass_rate": round(agg.holdout_pass_rate, 4),
    }
