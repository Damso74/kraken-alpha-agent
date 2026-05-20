"""Tests for walk-forward metrics (Phase 17)."""

from __future__ import annotations

from src.bot.walkforward_metrics import (
    WindowRunMetrics,
    aggregate_window_metrics,
    classify_walkforward_verdict,
)


def _holdout_run(wid: int, ret: float, dd: float = 5.0, trades: int = 10) -> WindowRunMetrics:
    return WindowRunMetrics(
        window_id=wid,
        period="holdout",
        net_return_pct=ret,
        max_drawdown_pct=dd,
        trade_count=trades,
        cost_drag_pct=10.0,
    )


def test_blocked_data_verdict() -> None:
    agg = aggregate_window_metrics([])
    v = classify_walkforward_verdict(agg, {"data_ok": False, "blocked_reason": "missing"})
    assert v.verdict == "blocked_data"


def test_insufficient_candles_verdict() -> None:
    agg = aggregate_window_metrics([])
    v = classify_walkforward_verdict(
        agg, {"data_ok": True, "plan_status": "insufficient_candles"}
    )
    assert v.verdict == "insufficient_candles"


def test_failed_walkforward_too_few_windows() -> None:
    agg = aggregate_window_metrics([_holdout_run(0, 5.0)])
    v = classify_walkforward_verdict(agg, {"data_ok": True})
    assert v.verdict == "failed_walkforward"


def test_paper_candidate_walkforward_strict() -> None:
    runs = [_holdout_run(i, 3.0 + i * 0.5, dd=8.0) for i in range(5)]
    agg = aggregate_window_metrics(runs)
    v = classify_walkforward_verdict(agg, {"data_ok": True})
    assert v.verdict == "paper_candidate_walkforward"


def test_unstable_when_low_positive_rate() -> None:
    runs = [
        _holdout_run(0, 5.0),
        _holdout_run(1, -2.0),
        _holdout_run(2, 1.0),
        _holdout_run(3, -1.0),
    ]
    agg = aggregate_window_metrics(runs)
    v = classify_walkforward_verdict(agg, {"data_ok": True})
    assert v.verdict in ("unstable", "weak", "failed_walkforward", "validation_candidate")


def test_aggregate_positive_window_rate() -> None:
    runs = [_holdout_run(0, 2.0), _holdout_run(1, -1.0), _holdout_run(2, 3.0)]
    agg = aggregate_window_metrics(runs)
    assert abs(agg.positive_window_rate - 2 / 3) < 1e-9
