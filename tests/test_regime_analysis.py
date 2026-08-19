"""Regression tests for :mod:`src.research.regime_analysis`.

Hand-built price series with analytically known regime labels. No network,
no filesystem, no subprocess.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from src.research.regime_analysis import (
    DEFAULT_BULL_THRESHOLD,
    DEFAULT_TREND_LOOKBACK,
    RegimeSummary,
    assign_calendar_regime,
    assign_calendar_regime_from_rows,
    assign_trend_regime,
    assign_volatility_regime,
    classify_regime_stability,
    summarize_by_regime,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _linear_closes(n: int, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + step * i for i in range(n)]


# ---------------------------------------------------------------------------
# assign_trend_regime
# ---------------------------------------------------------------------------


def test_assign_trend_regime_warmup_is_none() -> None:
    closes = _linear_closes(30, start=100.0, step=0.5)
    labels = assign_trend_regime(closes, lookback=5)
    assert labels[:5] == [None] * 5
    assert all(l is not None for l in labels[5:])


def test_assign_trend_regime_bull_on_uptrend() -> None:
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 110.0]
    labels = assign_trend_regime(
        closes,
        lookback=5,
        bull_threshold=DEFAULT_BULL_THRESHOLD,
        bear_threshold=DEFAULT_BULL_THRESHOLD,
    )
    assert labels[-1] == "bull"


def test_assign_trend_regime_bear_on_downtrend() -> None:
    closes = [110.0, 109.0, 108.0, 107.0, 106.0, 100.0]
    labels = assign_trend_regime(closes, lookback=5, bull_threshold=0.02, bear_threshold=0.02)
    assert labels[-1] == "bear"


def test_assign_trend_regime_sideways_on_flat() -> None:
    closes = [100.0] * 10
    labels = assign_trend_regime(closes, lookback=3)
    assert labels[-1] == "sideways"


def test_assign_trend_regime_no_lookahead() -> None:
    closes = [100.0] * 10 + [200.0] * 10
    labels = assign_trend_regime(closes, lookback=3, bull_threshold=0.05, bear_threshold=0.05)
    assert labels[9] == "sideways"
    assert labels[10] == "bull"


def test_assign_trend_regime_rejects_invalid_lookback() -> None:
    with pytest.raises(ValueError):
        assign_trend_regime([100.0], lookback=0)


def test_assign_trend_regime_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError):
        assign_trend_regime([100.0, 101.0], lookback=1, bull_threshold=-0.01)


# ---------------------------------------------------------------------------
# assign_volatility_regime
# ---------------------------------------------------------------------------


def test_assign_volatility_regime_warmup_is_none() -> None:
    closes = _linear_closes(40)
    labels = assign_volatility_regime(closes, lookback=5)
    assert labels[0] is None
    assert any(l is None for l in labels[:8])


def test_assign_volatility_regime_high_after_spike() -> None:
    calm = [100.0] * 25
    spike = [100.0, 120.0, 115.0, 118.0, 112.0, 116.0]
    closes = calm + spike
    labels = assign_volatility_regime(closes, lookback=5, quantile=0.5)
    assert labels[-1] == "high"


def test_assign_volatility_regime_low_on_flat_series() -> None:
    closes = [100.0] * 40
    labels = assign_volatility_regime(closes, lookback=5, quantile=0.5)
    assert labels[-1] == "low"


def test_assign_volatility_regime_no_lookahead() -> None:
    calm = [100.0] * 30
    spike_tail = [100.0, 150.0, 140.0, 130.0, 120.0]
    closes = calm + spike_tail
    labels = assign_volatility_regime(closes, lookback=5, quantile=0.5)
    idx_before_spike = len(calm) - 1
    assert labels[idx_before_spike] == "low"


def test_assign_volatility_regime_rejects_bad_lookback() -> None:
    with pytest.raises(ValueError):
        assign_volatility_regime([100.0, 101.0], lookback=1)


def test_assign_volatility_regime_rejects_bad_quantile() -> None:
    with pytest.raises(ValueError):
        assign_volatility_regime([100.0] * 10, lookback=3, quantile=1.0)


# ---------------------------------------------------------------------------
# assign_calendar_regime
# ---------------------------------------------------------------------------


def _ts(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 12, 0, tzinfo=UTC).timestamp())


def test_assign_calendar_regime_weekday_vs_weekend() -> None:
    monday = _ts(2024, 1, 1)
    saturday = _ts(2024, 1, 6)
    sunday = _ts(2024, 1, 7)
    labels = assign_calendar_regime([monday, saturday, sunday])
    assert labels == ["weekday", "weekend", "weekend"]


def test_assign_calendar_regime_from_rows() -> None:
    rows = [
        {"timestamp": _ts(2024, 1, 1), "close": 100.0},
        {"timestamp": _ts(2024, 1, 6), "close": 100.0},
    ]
    assert assign_calendar_regime_from_rows(rows) == ["weekday", "weekend"]


# ---------------------------------------------------------------------------
# summarize_by_regime
# ---------------------------------------------------------------------------


def test_summarize_by_regime_groups_and_stats() -> None:
    values = [0.01, 0.02, 0.03, -0.01, -0.02]
    regimes = ["bull", "bull", "bull", "bear", "bear"]
    summaries = summarize_by_regime(values, regimes)
    by_name = {s.regime: s for s in summaries}
    assert by_name["bull"].count == 3
    assert math.isclose(by_name["bull"].mean, 0.02, rel_tol=1e-9)
    assert by_name["bear"].count == 2
    assert math.isclose(by_name["bear"].mean, -0.015, rel_tol=1e-9)


def test_summarize_by_regime_skips_none_regime() -> None:
    values = [0.01, 0.02]
    regimes = [None, "bull"]
    summaries = summarize_by_regime(values, regimes)
    assert len(summaries) == 1
    assert summaries[0].regime == "bull"
    assert summaries[0].count == 1


def test_summarize_by_regime_respects_min_count() -> None:
    values = [0.01, 0.02, -0.01]
    regimes = ["bull", "bull", "bear"]
    summaries = summarize_by_regime(values, regimes, min_count=2)
    assert len(summaries) == 1
    assert summaries[0].regime == "bull"


def test_summarize_by_regime_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        summarize_by_regime([0.01], ["bull", "bear"])


# ---------------------------------------------------------------------------
# classify_regime_stability
# ---------------------------------------------------------------------------


def _summary(regime: str, count: int, mean: float) -> RegimeSummary:
    return RegimeSummary(
        regime=regime,
        count=count,
        mean=mean,
        median=mean,
        stdev=0.01 if count > 1 else None,
    )


def test_classify_regime_stability_stable_same_sign_tight_spread() -> None:
    summaries = (
        _summary("bull", 10, 0.010),
        _summary("bear", 10, 0.008),
    )
    result = classify_regime_stability(summaries, min_per_regime=5, max_spread_ratio=0.5)
    assert result.label == "stable"
    assert result.spread_ratio is not None
    assert result.spread_ratio <= 0.5


def test_classify_regime_stability_unstable_sign_flip() -> None:
    summaries = (
        _summary("bull", 10, 0.020),
        _summary("bear", 10, -0.015),
    )
    result = classify_regime_stability(summaries, min_per_regime=5)
    assert result.label == "unstable"
    assert "opposite signs" in result.notes


def test_classify_regime_stability_unstable_wide_spread() -> None:
    summaries = (
        _summary("high", 10, 0.050),
        _summary("low", 10, 0.005),
    )
    result = classify_regime_stability(
        summaries, min_per_regime=5, max_spread_ratio=0.2
    )
    assert result.label == "unstable"
    assert "spread_ratio" in result.notes


def test_classify_regime_stability_insufficient_data() -> None:
    summaries = (_summary("bull", 2, 0.01),)
    result = classify_regime_stability(summaries, min_per_regime=5)
    assert result.label == "insufficient_data"


def test_classify_regime_stability_single_regime() -> None:
    summaries = (
        _summary("bull", 10, 0.01),
        _summary("bear", 2, -0.02),
    )
    result = classify_regime_stability(summaries, min_per_regime=5)
    assert result.label == "single_regime"
    assert result.dominant_regime == "bull"


# ---------------------------------------------------------------------------
# Integration: end-to-end slice without lookahead
# ---------------------------------------------------------------------------


def test_regime_pipeline_on_hand_built_returns() -> None:
    closes = _linear_closes(50, start=100.0, step=0.2)
    trend = assign_trend_regime(closes, lookback=DEFAULT_TREND_LOOKBACK)
    returns = [0.005 if t == "bull" else 0.001 for t in trend]
    paired = [(r, t) for r, t in zip(returns, trend) if t is not None]
    values = [r for r, _ in paired]
    regimes = [t for _, t in paired]
    summaries = summarize_by_regime(values, regimes, min_count=5)
    stability = classify_regime_stability(summaries, min_per_regime=5)
    assert stability.label in {"stable", "single_regime", "unstable", "insufficient_data"}
    assert len(summaries) >= 1
