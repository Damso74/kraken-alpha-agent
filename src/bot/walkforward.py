"""Walk-forward rolling window split engine for paper-bot tournaments."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

PeriodName = Literal["train", "validation", "holdout"]

WALKFORWARD_PARAMS: dict[str, dict[str, int]] = {
    "1d": {"train": 365, "validation": 90, "holdout": 90, "step": 30},
    "4h": {"train": 365 * 6, "validation": 90 * 6, "holdout": 90 * 6, "step": 30 * 6},
    "1h": {"train": 365 * 24, "validation": 90 * 24, "holdout": 90 * 24, "step": 30 * 24},
}

DEFAULT_EMBARGO_BARS = 0


@dataclass(frozen=True)
class WindowPeriod:
    """Inclusive slice indices into the parent candle list."""

    name: PeriodName
    start: int
    end: int  # exclusive

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)


@dataclass
class WalkForwardWindow:
    """One rolling train / validation / holdout window."""

    window_id: int
    train: WindowPeriod
    validation: WindowPeriod
    holdout: WindowPeriod
    embargo_bars: int = 0

    def all_periods(self) -> tuple[WindowPeriod, WindowPeriod, WindowPeriod]:
        return (self.train, self.validation, self.holdout)


@dataclass
class WindowPlan:
    """Full plan for a candle series."""

    timeframe: str
    train_bars: int
    validation_bars: int
    holdout_bars: int
    step_bars: int
    embargo_bars: int
    candle_count: int
    windows: list[WalkForwardWindow] = field(default_factory=list)
    status: str = "ok"
    blocked_reason: str | None = None


def params_for_timeframe(timeframe: str) -> dict[str, int]:
    tf = timeframe.strip().lower()
    if tf not in WALKFORWARD_PARAMS:
        raise ValueError(f"unsupported timeframe for walk-forward: {timeframe}")
    return dict(WALKFORWARD_PARAMS[tf])


def min_candles_required(
    train_bars: int,
    validation_bars: int,
    holdout_bars: int,
    *,
    embargo_bars: int = DEFAULT_EMBARGO_BARS,
) -> int:
    """Minimum contiguous bars for at least one full window."""
    return train_bars + validation_bars + holdout_bars + 2 * embargo_bars


def apply_embargo_between_periods(
    train_end: int,
    validation_start: int,
    validation_end: int,
    holdout_start: int,
    *,
    embargo_bars: int,
) -> tuple[int, int, int]:
    """Shift validation/holdout starts forward to enforce embargo gaps."""
    val_start = max(validation_start, train_end + embargo_bars)
    hold_start = max(holdout_start, validation_end + embargo_bars)
    return train_end, val_start, hold_start


def assign_candles_to_periods(
    candles: Sequence[Any],
    window: WalkForwardWindow,
) -> dict[PeriodName, list[Any]]:
    """Slice candles for each period in a window."""
    out: dict[PeriodName, list[Any]] = {}
    for period in window.all_periods():
        out[period.name] = list(candles[period.start : period.end])
    return out


def validate_no_overlap(window: WalkForwardWindow) -> list[str]:
    """Return error strings if periods overlap or are out of order."""
    errors: list[str] = []
    periods = window.all_periods()
    for i, left in enumerate(periods):
        if left.start >= left.end:
            errors.append(f"{left.name}: empty or inverted slice [{left.start},{left.end})")
        for right in periods[i + 1 :]:
            if left.end > right.start:
                errors.append(
                    f"overlap {left.name}[{left.start},{left.end}) "
                    f"and {right.name}[{right.start},{right.end})"
                )
            if left.end + window.embargo_bars > right.start:
                errors.append(
                    f"embargo violation {left.name}->{right.name}: "
                    f"gap={right.start - left.end} < embargo={window.embargo_bars}"
                )
    return errors


def create_rolling_windows(
    candles: Sequence[Any],
    train_bars: int,
    validation_bars: int,
    holdout_bars: int,
    step_bars: int,
    *,
    embargo_bars: int = DEFAULT_EMBARGO_BARS,
    timeframe: str = "1d",
) -> WindowPlan:
    """Build rolling walk-forward windows; insufficient candles → empty plan."""
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

    windows: list[WalkForwardWindow] = []
    offset = 0
    window_id = 0
    window_span = train_bars + validation_bars + holdout_bars + 2 * embargo_bars

    while offset + window_span <= n:
        train_start = offset
        train_end = train_start + train_bars
        val_start = train_end + embargo_bars
        val_end = val_start + validation_bars
        hold_start = val_end + embargo_bars
        hold_end = hold_start + holdout_bars

        _, val_start, hold_start = apply_embargo_between_periods(
            train_end,
            val_start,
            val_end,
            hold_start,
            embargo_bars=embargo_bars,
        )
        val_end = val_start + validation_bars
        hold_end = hold_start + holdout_bars

        if hold_end > n:
            break

        w = WalkForwardWindow(
            window_id=window_id,
            train=WindowPeriod("train", train_start, train_end),
            validation=WindowPeriod("validation", val_start, val_end),
            holdout=WindowPeriod("holdout", hold_start, hold_end),
            embargo_bars=embargo_bars,
        )
        overlap_errors = validate_no_overlap(w)
        if overlap_errors:
            plan.status = "invalid_windows"
            plan.blocked_reason = "; ".join(overlap_errors)
            return plan
        windows.append(w)
        window_id += 1
        offset += step_bars

    if not windows:
        plan.status = "insufficient_candles"
        plan.blocked_reason = (
            f"no rolling windows fit candle_count={n} min_required={min_needed}"
        )
        return plan

    plan.windows = windows
    plan.status = "ok"
    return plan


def create_rolling_windows_for_timeframe(
    candles: Sequence[Any],
    timeframe: str,
    *,
    embargo_bars: int = DEFAULT_EMBARGO_BARS,
) -> WindowPlan:
    """Convenience wrapper using pre-declared timeframe params."""
    p = params_for_timeframe(timeframe)
    return create_rolling_windows(
        candles,
        p["train"],
        p["validation"],
        p["holdout"],
        p["step"],
        embargo_bars=embargo_bars,
        timeframe=timeframe,
    )


def summarize_windows(plan: WindowPlan) -> dict[str, Any]:
    """Human-readable summary for reports and CLI."""
    first_ts = None
    last_ts = None
    if plan.windows:
        # caller may pass dict candles with timestamp
        pass

    return {
        "timeframe": plan.timeframe,
        "status": plan.status,
        "blocked_reason": plan.blocked_reason,
        "candle_count": plan.candle_count,
        "train_bars": plan.train_bars,
        "validation_bars": plan.validation_bars,
        "holdout_bars": plan.holdout_bars,
        "step_bars": plan.step_bars,
        "embargo_bars": plan.embargo_bars,
        "windows_total": len(plan.windows),
        "min_candles_required": min_candles_required(
            plan.train_bars,
            plan.validation_bars,
            plan.holdout_bars,
            embargo_bars=plan.embargo_bars,
        ),
        "first_window_train_start": plan.windows[0].train.start if plan.windows else None,
        "last_window_holdout_end": plan.windows[-1].holdout.end if plan.windows else None,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
    }


def context_candles_for_period(
    candles: Sequence[Any],
    window: WalkForwardWindow,
    period: PeriodName,
    warmup_bars: int,
) -> list[Any]:
    """Return history + period slice so strategy warmup is satisfied."""
    if period == "train":
        return list(candles[window.train.start : window.train.end])
    if period == "validation":
        hist_start = max(0, window.validation.start - warmup_bars)
        return list(candles[hist_start : window.validation.end])
    # holdout — include train+validation history for warmup
    hist_start = max(0, window.holdout.start - warmup_bars)
    return list(candles[hist_start : window.holdout.end])


def eval_start_index_in_context(context: Sequence[Any], period: WindowPeriod) -> int:
    """Bar index within context where the evaluation period begins."""
    return max(0, period.start - (len(context) - (period.end - period.start)))
