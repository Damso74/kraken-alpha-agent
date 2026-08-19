"""Tests for backtest metrics and verdicts."""

from __future__ import annotations

from src.bot.metrics import (
    BacktestMetrics,
    RiskRunStats,
    compute_metrics,
    compute_verdict,
    metrics_to_dict,
)

# Deltas d'equity tels que le moteur les produit : un fill marque aux memes
# prix avant/apres ne laisse que le cout, jamais le resultat du trade.
FEE_ONLY_DELTAS = [-0.5, -0.5]


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


def test_cost_drag_undefined_instead_of_100_pct_sentinel() -> None:
    """Defaut #15 : sans PnL realise, cost_drag etait force a 100 %."""
    m = compute_metrics(
        equity_curve=[1000.0, 999.0],
        trade_pnls=FEE_ONLY_DELTAS,
        round_trip_pnls=[],
        fees_usd=1.0,
        slippage_drag_usd=0.0,
        starting_equity=1000.0,
    )
    assert m.cost_drag_undefined is True
    assert m.cost_drag_pct != 100.0
    assert metrics_to_dict(m)["cost_drag_undefined"] is True


def test_cost_drag_measured_against_realized_round_trips() -> None:
    """Le denominateur est le PnL realise, pas la somme des deltas de frais."""
    m = compute_metrics(
        equity_curve=[1000.0, 1080.0],
        trade_pnls=FEE_ONLY_DELTAS,
        round_trip_pnls=[100.0, -20.0],
        fees_usd=8.0,
        slippage_drag_usd=0.0,
        starting_equity=1000.0,
    )
    assert m.cost_drag_undefined is False
    assert m.cost_drag_pct == 10.0
    assert m.win_rate_pct == 50.0
    assert m.round_trip_count == 2


def test_undefined_cost_drag_is_not_a_cost_failure() -> None:
    """Un cout non mesurable ne doit pas declencher blocked_costs."""
    m = BacktestMetrics(
        trade_count=10,
        total_return_pct=2.0,
        max_drawdown_pct=10.0,
        cost_drag_pct=999.0,
        cost_drag_undefined=True,
    )
    v = compute_verdict(m, data_ok=True)
    assert v.verdict != "blocked_costs"


def test_win_rate_is_none_without_round_trip_information() -> None:
    """Defaut #8 : l'absence d'info doit etre explicite, pas un 0 % silencieux."""
    m = compute_metrics(
        equity_curve=[1000.0, 1010.0],
        trade_pnls=FEE_ONLY_DELTAS,
        round_trip_pnls=None,
        fees_usd=1.0,
        slippage_drag_usd=0.0,
        starting_equity=1000.0,
    )
    assert m.trade_count == 2
    assert m.win_rate_pct is None
    assert metrics_to_dict(m)["win_rate_pct"] is None
