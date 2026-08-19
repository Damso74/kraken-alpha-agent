"""Phase 24 walk-forward holdout sensitivity and validation gates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from src.bot.walkforward import (
    DEFAULT_EMBARGO_BARS,
    WalkForwardWindow,
    WindowPeriod,
    WindowPlan,
    create_rolling_windows,
    min_candles_required,
    params_for_timeframe,
    validate_no_overlap,
)
from src.bot.walkforward_metrics import (
    WalkForwardAggregate,
    WalkForwardVerdictResult,
    WindowRunMetrics,
    classify_walkforward_verdict,
)

HoldoutPct = float
WindowMode = Literal["rolling", "expanding"]

HOLDOUT_PCT_VARIANTS: tuple[HoldoutPct, ...] = (0.20, 0.30, 0.40)
MIN_BH_BEAT_HOLDOUT_WINDOWS = 2
MIN_HOLDOUT_TRADES_TOTAL = 8
MIN_HOLDOUT_TRADES_PER_WINDOW = 1
PHASE24_PAPER_CANDIDATE_FORBIDDEN = True


@dataclass(frozen=True)
class HoldoutSensitivitySpec:
    holdout_pct: HoldoutPct
    window_mode: WindowMode


def scaled_holdout_bars(timeframe: str, holdout_pct: HoldoutPct) -> int:
    """Holdout bar count from pct of canonical train+validation+holdout span."""
    p = params_for_timeframe(timeframe)
    span = p["train"] + p["validation"] + p["holdout"]
    return max(30, int(round(span * holdout_pct)))


def create_holdout_sensitivity_plan(
    candles: Sequence[Any],
    timeframe: str,
    holdout_pct: HoldoutPct,
    *,
    window_mode: WindowMode = "rolling",
    embargo_bars: int = DEFAULT_EMBARGO_BARS,
) -> WindowPlan:
    """Rolling or single expanding window plan with scaled holdout fraction."""
    p = params_for_timeframe(timeframe)
    holdout_bars = scaled_holdout_bars(timeframe, holdout_pct)
    train_bars = p["train"]
    validation_bars = p["validation"]
    step_bars = p["step"]

    if window_mode == "rolling":
        return create_rolling_windows(
            candles,
            train_bars,
            validation_bars,
            holdout_bars,
            step_bars,
            embargo_bars=embargo_bars,
            timeframe=timeframe,
        )

    n = len(candles)
    min_needed = min_candles_required(
        train_bars, validation_bars, holdout_bars, embargo_bars=embargo_bars
    )
    plan = WindowPlan(
        timeframe=timeframe,
        train_bars=train_bars,
        validation_bars=validation_bars,
        holdout_bars=holdout_bars,
        step_bars=step_bars,
        embargo_bars=embargo_bars,
        candle_count=n,
    )
    if n < min_needed:
        plan.status = "insufficient_candles"
        plan.blocked_reason = f"candle_count={n} < min_required={min_needed}"
        return plan

    train_end = n - validation_bars - holdout_bars - 2 * embargo_bars
    if train_end < train_bars // 2:
        plan.status = "insufficient_candles"
        plan.blocked_reason = (
            f"expanding train_end={train_end} < half canonical train={train_bars // 2}"
        )
        return plan

    val_start = train_end + embargo_bars
    val_end = val_start + validation_bars
    hold_start = val_end + embargo_bars
    hold_end = hold_start + holdout_bars
    if hold_end > n:
        plan.status = "insufficient_candles"
        plan.blocked_reason = f"expanding hold_end={hold_end} > n={n}"
        return plan

    w = WalkForwardWindow(
        window_id=0,
        train=WindowPeriod("train", 0, train_end),
        validation=WindowPeriod("validation", val_start, val_end),
        holdout=WindowPeriod("holdout", hold_start, hold_end),
        embargo_bars=embargo_bars,
    )
    overlap_errors = validate_no_overlap(w)
    if overlap_errors:
        plan.status = "invalid_windows"
        plan.blocked_reason = "; ".join(overlap_errors)
        return plan

    plan.windows = [w]
    plan.status = "ok"
    return plan


def _downgrade_paper_candidate(
    result: WalkForwardVerdictResult,
) -> WalkForwardVerdictResult:
    if result.verdict != "paper_candidate_walkforward":
        return result
    return WalkForwardVerdictResult(
        "validation_candidate",
        result.reasons + ["phase24_paper_candidate_forbidden"],
        aggregate=result.aggregate,
    )


def classify_phase24_sensitivity_verdict(
    agg: WalkForwardAggregate,
    context: Mapping[str, Any] | None = None,
) -> WalkForwardVerdictResult:
    """Phase 24 WF verdict: never promotes to paper_candidate; B&H gates for validation."""
    base = classify_walkforward_verdict(agg, context)
    base = _downgrade_paper_candidate(base)
    ctx = dict(context or {})

    if base.verdict in (
        "blocked_data",
        "insufficient_candles",
        "failed_walkforward",
    ):
        return base

    bh_beats = int(ctx.get("holdout_beats_bh_count", 0))
    bh_windows = int(ctx.get("holdout_bh_windows", 0))
    total_trades = int(ctx.get("total_trade_count", 0))
    strat_dd = float(ctx.get("full_max_drawdown_pct", agg.max_window_drawdown))
    bh_dd = float(ctx.get("bh_max_drawdown_pct", 0.0))
    excess_median = float(ctx.get("median_excess_vs_bh_pct", 0.0))
    full_excess_vs_bh = float(ctx.get("full_excess_vs_bh_pct", 0.0))

    extra: list[str] = []
    if bh_windows > 0 and bh_beats < MIN_BH_BEAT_HOLDOUT_WINDOWS:
        extra.append(
            f"holdout_beats_bh={bh_beats} < {MIN_BH_BEAT_HOLDOUT_WINDOWS}"
        )
    if bh_dd > 1e-9 and strat_dd >= bh_dd - 0.5:
        extra.append(f"drawdown_not_below_bh strat={strat_dd:.2f}% bh={bh_dd:.2f}%")
    if total_trades < MIN_HOLDOUT_TRADES_TOTAL:
        extra.append(f"total_trade_count={total_trades} < {MIN_HOLDOUT_TRADES_TOTAL}")
    if excess_median <= 0.0:
        extra.append(f"median_holdout_excess_vs_bh={excess_median:.2f}%")
    if full_excess_vs_bh <= 0.0:
        extra.append(f"full_excess_vs_bh={full_excess_vs_bh:.2f}%")

    overlay_only = bool(ctx.get("overlay_only_outperformance", False))
    if overlay_only:
        extra.append("overlay_only_outperformance")

    if (
        bh_beats >= MIN_BH_BEAT_HOLDOUT_WINDOWS
        and total_trades >= MIN_HOLDOUT_TRADES_TOTAL
        and (bh_dd <= 1e-9 or strat_dd < bh_dd - 0.5)
        and excess_median > 0.0
        and full_excess_vs_bh > 0.0
        and agg.median_net_return > 0.0
        and agg.holdout_pass_rate >= 0.50
        and not overlay_only
    ):
        return WalkForwardVerdictResult(
            "validation_candidate",
            base.reasons + ["phase24_bh_holdout_gates_pass"],
            aggregate=agg,
        )

    if extra:
        verdict = base.verdict
        if verdict == "validation_candidate":
            verdict = "weak"
        return WalkForwardVerdictResult(
            verdict,
            base.reasons + extra,
            aggregate=agg,
        )

    return base


def count_holdout_beats_bh(
    holdout_runs: Sequence[WindowRunMetrics],
    bh_holdout_returns: Sequence[float],
) -> tuple[int, float]:
    """Windows where strategy holdout return beats B&H on same slice."""
    beats = 0
    excess: list[float] = []
    for run, bh_ret in zip(holdout_runs, bh_holdout_returns, strict=False):
        ex = run.net_return_pct - float(bh_ret)
        excess.append(ex)
        if ex > 0.0 and run.trade_count >= MIN_HOLDOUT_TRADES_PER_WINDOW:
            beats += 1
    median_excess = 0.0
    if excess:
        from statistics import median

        median_excess = float(median(excess))
    return beats, median_excess
