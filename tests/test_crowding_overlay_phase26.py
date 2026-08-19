"""Phase 26C — crowding overlay (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.bot.crowding_overlay import (
    CrowdingOverlayStrategy,
    classify_crowding,
    compare_baseline_vs_overlay,
    precompute_crowding_states,
)
from src.bot.phase26_walkforward import classify_phase26_overlay_verdict


def _candles(n: int, step: int = 14400) -> list[dict]:
    t0 = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    return [
        {
            "timestamp": t0 + i * step,
            "open": 100.0 + i * 0.1,
            "high": 101.0 + i * 0.1,
            "low": 99.0 + i * 0.1,
            "close": 100.5 + i * 0.1,
            "volume": 1.0,
        }
        for i in range(n)
    ]


def test_classify_crowding_block() -> None:
    st = classify_crowding(3.0, 0.1)
    assert st.filter == "block"


def test_compare_overlay_risk_only() -> None:
    cmp = compare_baseline_vs_overlay(
        {"max_drawdown_pct": 20.0, "total_return_pct": 5.0},
        {"max_drawdown_pct": 12.0, "total_return_pct": 4.0},
    )
    assert cmp["improved_risk_only"] is True


def test_phase26_verdict_overlay_only() -> None:
    v = classify_phase26_overlay_verdict(
        {"data_ok": True, "total_return_pct": 5, "max_drawdown_pct": 20},
        {"data_ok": True, "total_return_pct": 4, "max_drawdown_pct": 12},
    )
    assert v == "overlay_only"


def test_crowding_overlay_warmup() -> None:
    from src.bot.phase23_presets import build_phase23_strategy

    inner = build_phase23_strategy("ema_crossover", "4h", "baseline")
    ov = CrowdingOverlayStrategy(inner, "4h")
    assert ov.warmup_bars() >= inner.warmup_bars()


def test_precompute_states_length() -> None:
    candles = _candles(100)
    fund = [{"timestamp": int(c["timestamp"]), "funding_rate": 0.0001} for c in candles[::3]]
    oi = [{"timestamp": int(c["timestamp"]), "open_interest": 1000.0} for c in candles[::3]]
    states = precompute_crowding_states(candles, fund, oi)
    assert len(states) == len(candles)
