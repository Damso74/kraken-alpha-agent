"""Regression tests for :mod:`src.research.event_study`.

The module is pure-Python and pure-function; the tests build hand-made
OHLC sequences where the metric values are known analytically and
assert against them. No network, no filesystem, no subprocess.
"""

from __future__ import annotations

import dataclasses
import math

import pytest

from src.research.event_study import (
    METRIC_REGISTRY,
    EventStudyResult,
    EventStudyRow,
    EventStudyWindow,
    make_post_event_windows,
    make_symmetric_windows,
    metric_log_return,
    metric_max_drawdown,
    metric_realized_vol,
    metric_simple_return,
    metric_volume_ratio,
    register_metric,
    run_event_study,
)

# ---------------------------------------------------------------------------
# Fixtures: deterministic OHLC sequences
# ---------------------------------------------------------------------------


def _row(ts: int, close: float, volume: float = 1.0) -> dict:
    """Minimal OHLC row honouring the contract used by the engine."""
    return {
        "timestamp": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
    }


@pytest.fixture
def linear_candles() -> list[dict]:
    """30 candles, close = 100 + i, volume = 1.0. One candle per hour."""
    return [_row(1700000000 + i * 3600, 100.0 + i, 1.0) for i in range(30)]


@pytest.fixture
def shock_candles() -> list[dict]:
    """40 hourly candles, flat at 100 then a +10% jump halfway through.

    Closes go 100, 100, ..., 100 (indices 0..19) then 110, 110, ..., 110
    (indices 20..39). Used as the canonical "event at index 20"
    fixture for the run_event_study tests.
    """
    closes = [100.0] * 20 + [110.0] * 20
    return [_row(1700000000 + i * 3600, c, 1.0) for i, c in enumerate(closes)]


# ---------------------------------------------------------------------------
# EventStudyWindow validation
# ---------------------------------------------------------------------------


def test_event_study_window_rejects_empty_label() -> None:
    with pytest.raises(ValueError):
        EventStudyWindow("", -1, 1)


def test_event_study_window_rejects_inverted_offsets() -> None:
    with pytest.raises(ValueError):
        EventStudyWindow("bad", 5, 1)


def test_event_study_window_length_includes_anchor() -> None:
    assert EventStudyWindow("around", -3, 3).length == 7
    assert EventStudyWindow("anchor", 0, 0).length == 1


def test_event_study_window_rejects_non_int_offsets() -> None:
    with pytest.raises(TypeError):
        EventStudyWindow("bad", 0.0, 1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Built-in metrics — analytical sanity checks
# ---------------------------------------------------------------------------


def test_metric_simple_return_two_closes() -> None:
    window = [_row(0, 100.0), _row(3600, 110.0)]
    assert metric_simple_return(window, []) == pytest.approx(0.10)


def test_metric_simple_return_returns_none_on_empty_window() -> None:
    assert metric_simple_return([], []) is None


def test_metric_log_return_matches_math_log() -> None:
    window = [_row(0, 100.0), _row(3600, 110.0)]
    assert metric_log_return(window, []) == pytest.approx(math.log(1.10))


def test_metric_realized_vol_constant_series_is_zero() -> None:
    window = [_row(i, 100.0) for i in range(10)]
    assert metric_realized_vol(window, []) == pytest.approx(0.0)


def test_metric_realized_vol_alternating_returns() -> None:
    """A two-step ±1 % series should have a non-zero realised vol."""
    closes = [100.0, 101.0, 100.0, 101.0, 100.0]
    window = [_row(i, c) for i, c in enumerate(closes)]
    rv = metric_realized_vol(window, [])
    assert rv is not None
    assert rv > 0.0


def test_metric_volume_ratio_basic() -> None:
    window = [_row(0, 100.0, volume=5.0), _row(3600, 100.0, volume=5.0)]
    baseline = [_row(-i, 100.0, volume=1.0) for i in range(1, 11)]
    assert metric_volume_ratio(window, baseline) == pytest.approx(5.0)


def test_metric_volume_ratio_returns_none_when_no_baseline() -> None:
    window = [_row(0, 100.0, volume=5.0)]
    assert metric_volume_ratio(window, []) is None


def test_metric_volume_ratio_returns_none_when_baseline_mean_zero() -> None:
    window = [_row(0, 100.0, volume=5.0)]
    baseline = [_row(-1, 100.0, volume=0.0), _row(-2, 100.0, volume=0.0)]
    assert metric_volume_ratio(window, baseline) is None


def test_metric_max_drawdown_always_non_positive() -> None:
    closes = [100.0, 110.0, 90.0, 95.0, 80.0, 120.0]
    window = [_row(i, c) for i, c in enumerate(closes)]
    dd = metric_max_drawdown(window, [])
    assert dd is not None
    assert dd <= 0.0
    assert dd == pytest.approx((80.0 - 110.0) / 110.0)


def test_metric_max_drawdown_monotone_up_is_zero() -> None:
    window = [_row(i, 100.0 + i) for i in range(10)]
    assert metric_max_drawdown(window, []) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Custom metric registration
# ---------------------------------------------------------------------------


def test_register_metric_round_trip() -> None:
    def constant_metric(_w, _b) -> float:
        return 42.0

    register_metric("constant_test", constant_metric)
    try:
        assert "constant_test" in METRIC_REGISTRY
        assert METRIC_REGISTRY["constant_test"]([], []) == 42.0
    finally:
        METRIC_REGISTRY.pop("constant_test", None)


def test_register_metric_rejects_non_callable() -> None:
    with pytest.raises(TypeError):
        register_metric("bad", "not-a-fn")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# run_event_study — anchoring and aggregation
# ---------------------------------------------------------------------------


def test_run_event_study_forward_as_of_anchoring(shock_candles: list[dict]) -> None:
    """Event at the shock boundary should produce a known +10 % return.

    The shock candle is at index 20 (timestamp = ``base + 20*3600``).
    A post-event window covering indices 1..1 (i.e. one candle right
    after the anchor) is just the close at index 21 vs the anchor at
    index 20 — both are 110, so the return is 0. The 1..3 window also
    stays at 110. The pre-event window -3..-1 covers closes 100/100/100,
    return 0 as well.

    The interesting cell is a window that *spans* the shock: -1..1
    covers indices 19, 20, 21 (closes 100, 110, 110) → 10 %.
    """
    base = shock_candles[0]["timestamp"]
    event_ts = base + 20 * 3600
    windows = (
        EventStudyWindow("post_1", 1, 1),
        EventStudyWindow("span_shock", -1, 1),
    )
    result = run_event_study(
        shock_candles,
        events=[event_ts],
        windows=windows,
        metrics=["return"],
        compute_baseline=False,
    )
    assert result.events_count == 1
    assert result.events_used == 1
    assert result.events_skipped_oob == 0
    row_post1 = result.row("return", "post_1")
    row_span = result.row("return", "span_shock")
    assert row_post1 is not None and row_post1.n_events == 1
    assert row_post1.mean == pytest.approx(0.0)
    assert row_span is not None and row_span.n_events == 1
    assert row_span.mean == pytest.approx(0.10)


def test_run_event_study_event_before_first_candle_is_anchored_at_zero(
    linear_candles: list[dict],
) -> None:
    """An event earlier than every candle anchors at index 0."""
    early_ts = linear_candles[0]["timestamp"] - 86_400
    result = run_event_study(
        linear_candles,
        events=[early_ts],
        windows=[EventStudyWindow("post_2", 1, 2)],
        metrics=["return"],
        compute_baseline=False,
    )
    assert result.events_count == 1
    assert result.events_used == 1
    row = result.row("return", "post_2")
    assert row is not None
    assert row.n_events == 1


def test_run_event_study_event_after_last_candle_is_skipped(
    linear_candles: list[dict],
) -> None:
    late_ts = linear_candles[-1]["timestamp"] + 86_400
    result = run_event_study(
        linear_candles,
        events=[late_ts],
        windows=[EventStudyWindow("post_2", 1, 2)],
        metrics=["return"],
        compute_baseline=False,
    )
    assert result.events_count == 1
    assert result.events_used == 0
    assert result.events_skipped_oob == 1


def test_run_event_study_truncated_at_boundary_is_skipped(
    linear_candles: list[dict],
) -> None:
    """A window that runs past the last candle is dropped, not partial."""
    near_end_ts = linear_candles[-2]["timestamp"]
    result = run_event_study(
        linear_candles,
        events=[near_end_ts],
        windows=[EventStudyWindow("post_5", 1, 5)],
        metrics=["return"],
        compute_baseline=False,
    )
    row = result.row("return", "post_5")
    assert row is not None
    assert row.n_events == 0
    assert result.events_used == 0
    assert result.events_skipped_oob == 1


def test_run_event_study_three_events_aggregate(linear_candles: list[dict]) -> None:
    """Three events on a constant +1 / candle drift produce identical returns."""
    ts = [linear_candles[i]["timestamp"] for i in (5, 10, 15)]
    result = run_event_study(
        linear_candles,
        events=ts,
        windows=[EventStudyWindow("post_5", 1, 5)],
        metrics=["return"],
        compute_baseline=False,
    )
    row = result.row("return", "post_5")
    assert row is not None
    assert row.n_events == 3
    expected = (1.0) * 4 / (100.0 + 5 + 1)
    actual = row.mean
    assert actual > 0.0
    expected_at_5 = (110 - 106) / 106
    expected_at_10 = (115 - 111) / 111
    expected_at_15 = (120 - 116) / 116
    assert actual == pytest.approx(
        (expected_at_5 + expected_at_10 + expected_at_15) / 3
    )
    assert row.n_positive == 3
    assert row.hit_rate == pytest.approx(1.0)
    del expected


def test_run_event_study_multiple_metrics() -> None:
    """Same anchor, two metrics, one row per (metric, window)."""
    closes = [100.0] * 10 + [105.0] * 10
    candles = [_row(1700000000 + i * 3600, c, volume=1.0 + i) for i, c in enumerate(closes)]
    event_ts = candles[10]["timestamp"]
    result = run_event_study(
        candles,
        events=[event_ts],
        windows=[EventStudyWindow("post_5", 1, 5)],
        metrics=["return", "realized_vol", "volume_ratio"],
        baseline_lookback_candles=5,
        compute_baseline=False,
    )
    assert len(result.rows) == 3
    assert {r.metric for r in result.rows} == {"return", "realized_vol", "volume_ratio"}
    for r in result.rows:
        assert r.window_label == "post_5"


def test_run_event_study_rejects_unknown_metric(linear_candles: list[dict]) -> None:
    with pytest.raises(KeyError):
        run_event_study(
            linear_candles,
            events=[linear_candles[0]["timestamp"]],
            windows=[EventStudyWindow("post_1", 1, 1)],
            metrics=["unknown_metric"],
        )


def test_run_event_study_rejects_empty_windows(linear_candles: list[dict]) -> None:
    with pytest.raises(ValueError):
        run_event_study(
            linear_candles,
            events=[],
            windows=[],
            metrics=["return"],
        )


def test_run_event_study_inline_custom_metric(linear_candles: list[dict]) -> None:
    def first_close(window, _baseline) -> float:
        return float(window[0]["close"])

    event_ts = linear_candles[5]["timestamp"]
    result = run_event_study(
        linear_candles,
        events=[event_ts],
        windows=[EventStudyWindow("post_1", 1, 1)],
        metrics=[("first_close", first_close)],
        compute_baseline=False,
    )
    row = result.row("first_close", "post_1")
    assert row is not None
    assert row.mean == pytest.approx(106.0)


def test_run_event_study_baseline_is_computed_when_requested(
    linear_candles: list[dict],
) -> None:
    event_ts = linear_candles[5]["timestamp"]
    result = run_event_study(
        linear_candles,
        events=[event_ts],
        windows=[EventStudyWindow("post_5", 1, 5)],
        metrics=["return"],
        compute_baseline=True,
    )
    assert "return" in result.baseline
    assert result.baseline["return"] != 0.0


def test_run_event_study_normalizes_unsorted_input() -> None:
    """Closes are 100..109. Event anchors at index 5 (close=105) after
    re-sorting. Window post_3 = candles at indices 6,7,8 (closes
    106, 107, 108). The simple_return metric is window-internal:
    (window_last_close - window_first_close) / window_first_close =
    (108 - 106) / 106. This test guards against silently
    forgetting to sort the input."""
    rows = [_row(1700000000 + i * 3600, 100.0 + i) for i in range(10)]
    shuffled = [rows[3], rows[0], rows[7], rows[5], rows[1], rows[2], rows[4], rows[6], rows[8], rows[9]]
    result = run_event_study(
        shuffled,
        events=[rows[5]["timestamp"]],
        windows=[EventStudyWindow("post_3", 1, 3)],
        metrics=["return"],
        compute_baseline=False,
    )
    row = result.row("return", "post_3")
    assert row is not None
    assert row.n_events == 1
    assert row.mean == pytest.approx((108.0 - 106.0) / 106.0)


def test_run_event_study_drops_rows_without_close_or_timestamp() -> None:
    rows = [
        _row(1700000000, 100.0),
        {"timestamp": 1700003600},
        _row(1700007200, 102.0),
        {"close": 103.0},
        _row(1700010800, 104.0),
    ]
    result = run_event_study(
        rows,
        events=[1700003600],
        windows=[EventStudyWindow("post_1", 1, 1)],
        metrics=["return"],
        compute_baseline=False,
    )
    assert result.candles_count == 3


# ---------------------------------------------------------------------------
# Convenience factories
# ---------------------------------------------------------------------------


def test_make_post_event_windows_shapes() -> None:
    windows = make_post_event_windows("post", [6, 24, 72])
    assert [w.label for w in windows] == ["post_6", "post_24", "post_72"]
    assert [w.start_offset for w in windows] == [1, 1, 1]
    assert [w.end_offset for w in windows] == [6, 24, 72]


def test_make_post_event_windows_rejects_zero() -> None:
    with pytest.raises(ValueError):
        make_post_event_windows("p", [0])


def test_make_symmetric_windows_labels_have_signs() -> None:
    windows = make_symmetric_windows("h", [-6, -1, 0, 1, 6])
    assert [w.label for w in windows] == ["h-6", "h-1", "h0", "h+1", "h+6"]
    for w in windows:
        assert w.start_offset == w.end_offset
        assert w.length == 1


def test_make_symmetric_windows_rejects_non_int() -> None:
    with pytest.raises(TypeError):
        make_symmetric_windows("h", [1.5])  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# EventStudyResult helpers
# ---------------------------------------------------------------------------


def test_event_study_result_row_lookup_returns_none_on_miss(
    linear_candles: list[dict],
) -> None:
    result = run_event_study(
        linear_candles,
        events=[linear_candles[5]["timestamp"]],
        windows=[EventStudyWindow("post_1", 1, 1)],
        metrics=["return"],
        compute_baseline=False,
    )
    assert result.row("return", "post_1") is not None
    assert result.row("return", "post_99") is None
    assert result.row("volume_ratio", "post_1") is None


def test_event_study_row_hit_rate_zero_when_no_events() -> None:
    row = EventStudyRow(
        metric="return",
        window_label="post_1",
        n_events=0,
        n_positive=0,
        mean=0.0,
        median=0.0,
        std=0.0,
        q25=0.0,
        q75=0.0,
        t_stat=None,
        p_value_approx=None,
    )
    assert row.hit_rate == 0.0


def test_event_study_t_stat_is_none_for_single_event(linear_candles: list[dict]) -> None:
    """Stdev is undefined for n=1, so t_stat / p_value must be None."""
    result = run_event_study(
        linear_candles,
        events=[linear_candles[5]["timestamp"]],
        windows=[EventStudyWindow("post_5", 1, 5)],
        metrics=["return"],
        compute_baseline=False,
    )
    row = result.row("return", "post_5")
    assert row is not None
    assert row.n_events == 1
    assert row.t_stat is None
    assert row.p_value_approx is None


def test_event_study_result_is_immutable(linear_candles: list[dict]) -> None:
    result = run_event_study(
        linear_candles,
        events=[linear_candles[5]["timestamp"]],
        windows=[EventStudyWindow("post_1", 1, 1)],
        metrics=["return"],
        compute_baseline=False,
    )
    assert isinstance(result, EventStudyResult)
    # Le gel doit venir de ``@dataclass(frozen=True)`` : un ``Exception`` nu
    # passerait aussi sur un simple AttributeError ou TypeError sans rapport.
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.events_count = 999  # type: ignore[misc]
