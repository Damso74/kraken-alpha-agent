"""Tests for backtest metrics and verdicts."""

from __future__ import annotations

from src.bot.metrics import BacktestMetrics, RiskRunStats, compute_verdict


def test_insufficient_trades_verdict() -> None:
    m = BacktestMetrics(trade_count=2, total_return_pct=10.0)
    v = compute_verdict(m, data_ok=True)
    assert v.verdict == "insufficient_trades"


def test_paper_candidate_verdict() -> None:
    m = BacktestMetrics(
        trade_count=10,
        total_return_pct=2.0,
        max_drawdown_pct=10.0,
        cost_drag_pct=5.0,
    )
    v = compute_verdict(m, data_ok=True)
    assert v.verdict == "paper_candidate"


def test_micro_live_off_by_default() -> None:
    m = BacktestMetrics(trade_count=20, total_return_pct=50.0, sharpe_ratio=2.0, max_drawdown_pct=5.0)
    v = compute_verdict(m, data_ok=True, allow_micro_live=False)
    assert v.verdict == "paper_candidate"
    assert not v.micro_live_enabled


def test_single_risk_deny_does_not_block() -> None:
    m = BacktestMetrics(
        trade_count=10,
        total_return_pct=2.0,
        max_drawdown_pct=10.0,
        cost_drag_pct=5.0,
    )
    stats = RiskRunStats(risk_denials_count=1, risk_checks_count=20)
    v = compute_verdict(m, data_ok=True, risk_stats=stats)
    assert v.verdict == "paper_candidate"


def test_high_risk_denial_rate_blocks() -> None:
    m = BacktestMetrics(trade_count=10, total_return_pct=2.0, max_drawdown_pct=10.0)
    stats = RiskRunStats(risk_denials_count=8, risk_checks_count=10)
    v = compute_verdict(m, data_ok=True, risk_stats=stats)
    assert v.verdict == "blocked_risk"
    assert any("risk_denial_rate" in r for r in v.reasons)


def test_max_drawdown_exceeded_blocks_risk() -> None:
    m = BacktestMetrics(trade_count=10, total_return_pct=2.0, max_drawdown_pct=18.0)
    v = compute_verdict(m, data_ok=True, risk_stats=RiskRunStats())
    assert v.verdict == "blocked_risk"
    assert any("max_drawdown_pct" in r for r in v.reasons)


def test_safety_stop_blocks_risk() -> None:
    m = BacktestMetrics(trade_count=10, total_return_pct=2.0, max_drawdown_pct=10.0)
    stats = RiskRunStats(stopped_by_risk=True)
    v = compute_verdict(m, data_ok=True, risk_stats=stats)
    assert v.verdict == "blocked_risk"
    assert "safety_stop" in v.reasons
