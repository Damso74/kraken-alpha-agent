"""Tests for Phase 23 risk-adjusted metrics."""

from __future__ import annotations

from src.bot.risk_adjusted_metrics import (
    calmar_like,
    compute_risk_adjusted_bundle,
    drawdown_reduction_vs_bh,
    risk_adjusted_alpha,
    ulcer_index_proxy,
)


def test_calmar_like_positive() -> None:
    assert calmar_like(10.0, 5.0) == 2.0


def test_drawdown_reduction_vs_bh() -> None:
    assert drawdown_reduction_vs_bh(8.0, 15.0) == 7.0


def test_risk_adjusted_alpha() -> None:
    assert abs(risk_adjusted_alpha(5.0, 2.0, 10.0) - 0.3) < 1e-9


def test_ulcer_index_proxy_flat() -> None:
    eq = [100.0] * 20
    assert ulcer_index_proxy(eq) == 0.0


def test_compute_risk_adjusted_bundle_keys() -> None:
    eq = [100.0, 101.0, 99.0, 102.0]
    bundle = compute_risk_adjusted_bundle(
        equity_curve=eq,
        strategy_return_pct=2.0,
        strategy_max_dd_pct=5.0,
        bh_return_pct=1.0,
        bh_max_dd_pct=8.0,
        journal=None,
        warmup_bars=1,
        total_bars=4,
    )
    assert "calmar_like" in bundle
    assert "risk_adjusted_alpha" in bundle
    assert bundle["drawdown_reduction_vs_bh"] == 3.0
