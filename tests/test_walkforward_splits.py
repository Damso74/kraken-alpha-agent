"""Tests for walk-forward split engine (Phase 17)."""

from __future__ import annotations

from src.bot.walkforward import (
    apply_embargo_between_periods,
    assign_candles_to_periods,
    create_rolling_windows,
    create_rolling_windows_for_timeframe,
    min_candles_required,
    params_for_timeframe,
    summarize_windows,
    validate_no_overlap,
    WalkForwardWindow,
    WindowPeriod,
)


def _candles(n: int) -> list[dict]:
    return [{"timestamp": i, "close": 100.0 + i * 0.01} for i in range(n)]


def test_params_for_timeframe_1d() -> None:
    p = params_for_timeframe("1d")
    assert p["train"] == 365
    assert p["validation"] == 90
    assert p["holdout"] == 90
    assert p["step"] == 30


def test_params_for_timeframe_4h() -> None:
    p = params_for_timeframe("4h")
    assert p["train"] == 365 * 6


def test_insufficient_candles_returns_blocked_plan() -> None:
    plan = create_rolling_windows(_candles(100), 365, 90, 90, 30, timeframe="1d")
    assert plan.status == "insufficient_candles"
    assert plan.windows == []
    assert plan.blocked_reason is not None


def test_create_rolling_windows_produces_non_overlapping() -> None:
    n = min_candles_required(50, 20, 20) + 40
    candles = _candles(n)
    plan = create_rolling_windows(candles, 50, 20, 20, 10, timeframe="1d")
    assert plan.status == "ok"
    assert len(plan.windows) >= 1
    for w in plan.windows:
        assert validate_no_overlap(w) == []


def test_assign_candles_to_periods_lengths() -> None:
    candles = _candles(200)
    plan = create_rolling_windows(candles, 80, 40, 40, 20, timeframe="1d")
    w = plan.windows[0]
    parts = assign_candles_to_periods(candles, w)
    assert len(parts["train"]) == 80
    assert len(parts["validation"]) == 40
    assert len(parts["holdout"]) == 40


def test_embargo_shifts_starts() -> None:
    _, val_start, hold_start = apply_embargo_between_periods(
        100, 100, 130, 130, embargo_bars=5
    )
    assert val_start == 105
    assert hold_start == 135


def test_summarize_windows_fields() -> None:
    candles = _candles(min_candles_required(50, 20, 20) + 10)
    plan = create_rolling_windows(candles, 50, 20, 20, 10, timeframe="1d")
    summary = summarize_windows(plan)
    assert summary["windows_total"] >= 1
    assert summary["timeframe"] == "1d"


def test_create_rolling_windows_for_timeframe_1h() -> None:
    p = params_for_timeframe("1h")
    needed = min_candles_required(p["train"], p["validation"], p["holdout"])
    plan = create_rolling_windows_for_timeframe(_candles(needed - 1), "1h")
    assert plan.status == "insufficient_candles"


def test_validate_no_overlap_detects_bad_window() -> None:
    w = WalkForwardWindow(
        window_id=0,
        train=WindowPeriod("train", 0, 50),
        validation=WindowPeriod("validation", 40, 70),
        holdout=WindowPeriod("holdout", 60, 90),
    )
    errors = validate_no_overlap(w)
    assert errors
