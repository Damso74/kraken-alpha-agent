"""Phase 15 metrics and verdict classifier tests."""

from __future__ import annotations

from src.bot.metrics import (
    BacktestMetrics,
    classify_strategy_verdict,
    compute_verdict,
)


def test_insufficient_trades_1h_threshold() -> None:
    m = BacktestMetrics(trade_count=15, candle_count=300, usable_bars=250)
    v = classify_strategy_verdict(
        m,
        {"timeframe": "1h", "data_ok": True, "candle_count": 300, "usable_bars": 250},
    )
    assert v.verdict == "insufficient_trades"


def test_insufficient_candles() -> None:
    m = BacktestMetrics(trade_count=0, candle_count=10, usable_bars=5)
    v = classify_strategy_verdict(
        m,
        {"timeframe": "4h", "data_ok": True, "candle_count": 10, "usable_bars": 5},
    )
    assert v.verdict == "insufficient_candles"


def test_blocked_data() -> None:
    m = BacktestMetrics()
    v = classify_strategy_verdict(m, {"data_ok": False, "blocked_reason": "missing cache"})
    assert v.verdict == "blocked_data"


def test_paper_candidate_never_micro_live() -> None:
    m = BacktestMetrics(
        trade_count=20,
        total_return_pct=10.0,
        max_drawdown_pct=8.0,
        cost_drag_pct=5.0,
        sharpe_ratio=1.5,
        candle_count=400,
        usable_bars=350,
    )
    v = classify_strategy_verdict(
        m,
        {"timeframe": "1d", "data_ok": True, "candle_count": 400, "usable_bars": 350},
    )
    assert v.verdict == "paper_candidate"
    assert v.verdict != "micro_live_candidate"


def test_weak_between_kill_and_paper() -> None:
    m = BacktestMetrics(
        trade_count=10,
        total_return_pct=-8.0,
        max_drawdown_pct=12.0,
        cost_drag_pct=5.0,
        sharpe_ratio=0.1,
        candle_count=200,
        usable_bars=180,
    )
    v = classify_strategy_verdict(
        m,
        {"timeframe": "1d", "data_ok": True, "candle_count": 200, "usable_bars": 180},
    )
    assert v.verdict == "weak"


def test_compute_verdict_phase14_compat() -> None:
    m = BacktestMetrics(trade_count=10, total_return_pct=2.0, max_drawdown_pct=10.0, cost_drag_pct=5.0)
    v = compute_verdict(m, data_ok=True, candle_count=0, usable_bars=0)
    assert v.verdict == "paper_candidate"
