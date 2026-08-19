"""Regression tests for :mod:`src.research.placebo`.

The harness is small but the corrections (Bonferroni, Benjamini–Hochberg)
have textbook-known answers — we test against them, not against the
implementation. Random helpers are pinned with explicit seeds and
checked for stability across runs.
"""

from __future__ import annotations

import math

import pytest

from src.research.placebo import (
    BenjaminiHochbergResult,
    EmpiricalPValueResult,
    PlaceboBootstrapResult,
    benjamini_hochberg,
    bonferroni_threshold,
    empirical_p_value,
    random_events_from_candles,
    run_placebo_bootstrap,
    shift_events_in_time,
    shuffle_labels,
)

# ---------------------------------------------------------------------------
# shift_events_in_time
# ---------------------------------------------------------------------------


def test_shift_events_in_time_translates_each_event() -> None:
    events = [1_700_000_000, 1_700_086_400, 1_700_172_800]
    shifted = shift_events_in_time(events, delta_seconds=86_400)
    assert shifted == [1_700_086_400, 1_700_172_800, 1_700_259_200]


def test_shift_events_in_time_preserves_cardinality_when_all_valid() -> None:
    events = list(range(1_700_000_000, 1_700_000_000 + 10 * 3600, 3600))
    shifted = shift_events_in_time(events, delta_seconds=-3600)
    assert len(shifted) == len(events)


def test_shift_events_in_time_drops_non_int_inputs() -> None:
    events = [1_700_000_000, "not-an-int", None, 1_700_086_400]
    shifted = shift_events_in_time(events, delta_seconds=3600)  # type: ignore[arg-type]
    assert shifted == [1_700_003_600, 1_700_090_000]


def test_shift_events_in_time_rejects_float_delta() -> None:
    with pytest.raises(TypeError):
        shift_events_in_time([1_700_000_000], delta_seconds=3600.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# random_events_from_candles
# ---------------------------------------------------------------------------


def test_random_events_from_candles_deterministic_with_seed() -> None:
    pool = list(range(1_700_000_000, 1_700_000_000 + 100 * 3600, 3600))
    picks_a = random_events_from_candles(pool, n_events=10, seed=42)
    picks_b = random_events_from_candles(pool, n_events=10, seed=42)
    assert picks_a == picks_b


def test_random_events_from_candles_returns_sorted_ascending() -> None:
    pool = list(range(1_700_000_000, 1_700_000_000 + 100 * 3600, 3600))
    picks = random_events_from_candles(pool, n_events=20, seed=123)
    assert picks == sorted(picks)


def test_random_events_from_candles_no_duplicates_by_default() -> None:
    pool = list(range(1_700_000_000, 1_700_000_000 + 100 * 3600, 3600))
    picks = random_events_from_candles(pool, n_events=50, seed=7)
    assert len(picks) == len(set(picks))


def test_random_events_from_candles_allows_duplicates_when_requested() -> None:
    pool = [1_700_000_000, 1_700_003_600]
    picks = random_events_from_candles(
        pool, n_events=20, seed=1, allow_duplicates=True
    )
    assert len(picks) == 20
    assert set(picks) <= set(pool)


def test_random_events_from_candles_rejects_oversampling_without_duplicates() -> None:
    pool = list(range(10))
    with pytest.raises(ValueError):
        random_events_from_candles(pool, n_events=20, seed=1)


def test_random_events_from_candles_zero_events_returns_empty() -> None:
    pool = list(range(1_700_000_000, 1_700_000_000 + 10 * 3600, 3600))
    assert random_events_from_candles(pool, n_events=0, seed=1) == []


def test_random_events_from_candles_empty_pool_returns_empty() -> None:
    assert random_events_from_candles([], n_events=5, seed=1) == []


def test_random_events_from_candles_negative_n_raises() -> None:
    with pytest.raises(ValueError):
        random_events_from_candles([1, 2, 3], n_events=-1, seed=1)


# ---------------------------------------------------------------------------
# shuffle_labels
# ---------------------------------------------------------------------------


def test_shuffle_labels_preserves_multiset() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    shuffled = shuffle_labels(values, seed=99)
    assert sorted(shuffled) == sorted(values)


def test_shuffle_labels_deterministic_with_seed() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    s1 = shuffle_labels(values, seed=42)
    s2 = shuffle_labels(values, seed=42)
    assert s1 == s2


def test_shuffle_labels_does_not_mutate_input() -> None:
    values = [1.0, 2.0, 3.0]
    original = list(values)
    shuffle_labels(values, seed=1)
    assert values == original


def test_shuffle_labels_different_seed_gives_different_order() -> None:
    values = list(range(20))
    s1 = shuffle_labels([float(v) for v in values], seed=1)
    s2 = shuffle_labels([float(v) for v in values], seed=2)
    assert s1 != s2


# ---------------------------------------------------------------------------
# bonferroni_threshold
# ---------------------------------------------------------------------------


def test_bonferroni_threshold_basic() -> None:
    assert bonferroni_threshold(0.05, 10) == pytest.approx(0.005)


def test_bonferroni_threshold_rejects_invalid_alpha() -> None:
    with pytest.raises(ValueError):
        bonferroni_threshold(0.0, 10)
    with pytest.raises(ValueError):
        bonferroni_threshold(1.0, 10)
    with pytest.raises(ValueError):
        bonferroni_threshold(-0.1, 10)


def test_bonferroni_threshold_rejects_invalid_n() -> None:
    with pytest.raises(ValueError):
        bonferroni_threshold(0.05, 0)
    with pytest.raises(ValueError):
        bonferroni_threshold(0.05, -5)


# ---------------------------------------------------------------------------
# benjamini_hochberg
# ---------------------------------------------------------------------------


def test_benjamini_hochberg_textbook_example() -> None:
    """Standard BH example: 10 p-values, alpha=0.05.

    The example is a slight rewording of the canonical BH 1995
    illustration: ascending p-values [0.001, 0.008, 0.039, 0.041,
    0.042, 0.060, 0.074, 0.205, 0.212, 0.216]. The BH cut-off at
    alpha=0.05 keeps the k where p_(k) <= k/m * alpha. Here:

    - k=1: p=0.001 <= 1/10*0.05 = 0.005 → keep
    - k=2: 0.008 <= 0.010 → keep
    - k=3: 0.039 <= 0.015 → fail
    - k=4: 0.041 <= 0.020 → fail
    - k=5: 0.042 <= 0.025 → fail

    The largest k with p_(k) <= k/m*alpha is k=2, so the first two
    ordered tests are rejected; in original order they correspond to
    indices 0 and 1 (the input is already sorted).
    """
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.060, 0.074, 0.205, 0.212, 0.216]
    result = benjamini_hochberg(p, alpha=0.05)
    assert isinstance(result, BenjaminiHochbergResult)
    assert result.n_rejected == 2
    assert result.rejected[0] is True
    assert result.rejected[1] is True
    assert all(not r for r in result.rejected[2:])


def test_benjamini_hochberg_preserves_input_order() -> None:
    """The rejected mask must align with the *input* order."""
    p = [0.5, 0.001, 0.4, 0.008]
    result = benjamini_hochberg(p, alpha=0.05)
    assert result.rejected[0] is False
    assert result.rejected[1] is True
    assert result.rejected[2] is False
    assert result.rejected[3] is True


def test_benjamini_hochberg_q_values_are_monotone_in_p_rank() -> None:
    """In sorted-p order, the BH q-values must be non-decreasing."""
    p = [0.001, 0.002, 0.01, 0.04, 0.05, 0.1, 0.2, 0.5, 0.8, 0.9]
    result = benjamini_hochberg(p, alpha=0.05)
    indexed = sorted(enumerate(p), key=lambda x: x[1])
    q_sorted = [result.q_values[i] for i, _ in indexed]
    for j in range(1, len(q_sorted)):
        assert q_sorted[j] + 1e-12 >= q_sorted[j - 1]


def test_benjamini_hochberg_q_values_bounded_in_unit_interval() -> None:
    p = [0.001, 0.5, 0.9, 0.95, 0.99]
    result = benjamini_hochberg(p, alpha=0.05)
    for q in result.q_values:
        assert 0.0 <= q <= 1.0


def test_benjamini_hochberg_empty_input() -> None:
    result = benjamini_hochberg([], alpha=0.05)
    assert result.n_rejected == 0
    assert result.q_values == ()
    assert result.rejected == ()


def test_benjamini_hochberg_rejects_invalid_p() -> None:
    with pytest.raises(ValueError):
        benjamini_hochberg([0.05, -0.1], alpha=0.05)
    with pytest.raises(ValueError):
        benjamini_hochberg([0.05, 1.5], alpha=0.05)
    with pytest.raises(ValueError):
        benjamini_hochberg([0.05, float("nan")], alpha=0.05)
    with pytest.raises(ValueError):
        benjamini_hochberg([0.05, None], alpha=0.05)  # type: ignore[list-item]


def test_benjamini_hochberg_rejects_invalid_alpha() -> None:
    with pytest.raises(ValueError):
        benjamini_hochberg([0.05, 0.1], alpha=0.0)
    with pytest.raises(ValueError):
        benjamini_hochberg([0.05, 0.1], alpha=1.0)


# ---------------------------------------------------------------------------
# empirical_p_value
# ---------------------------------------------------------------------------


def test_empirical_p_value_at_median_is_around_one() -> None:
    placebos = [float(i) for i in range(100)]
    r = empirical_p_value(observed=49.5, placebo_values=placebos)
    assert r.two_sided > 0.9
    assert 49.0 <= r.percentile_rank <= 51.0


def test_empirical_p_value_extreme_observation_gives_small_two_sided() -> None:
    placebos = [float(i) for i in range(100)]
    r = empirical_p_value(observed=1_000.0, placebo_values=placebos)
    assert r.two_sided < 0.05
    assert r.percentile_rank == 100.0
    assert r.one_sided_greater == pytest.approx(1.0 / (1 + 100))


def test_empirical_p_value_returns_smoothed_p_never_zero() -> None:
    placebos = [0.0] * 50
    r = empirical_p_value(observed=10.0, placebo_values=placebos)
    assert r.one_sided_greater > 0.0


def test_empirical_p_value_drops_non_finite_placebos() -> None:
    placebos = [1.0, float("nan"), 2.0, float("inf"), 3.0]
    r = empirical_p_value(observed=2.0, placebo_values=placebos)
    assert r.n_placebos == 3


def test_empirical_p_value_rejects_empty_after_dropping() -> None:
    with pytest.raises(ValueError):
        empirical_p_value(observed=1.0, placebo_values=[float("nan"), float("inf")])


def test_empirical_p_value_rejects_non_finite_observed() -> None:
    with pytest.raises(ValueError):
        empirical_p_value(observed=float("nan"), placebo_values=[1.0, 2.0])


def test_empirical_p_value_result_is_immutable() -> None:
    r = empirical_p_value(observed=1.0, placebo_values=[0.0, 0.5, 1.0])
    assert isinstance(r, EmpiricalPValueResult)
    with pytest.raises(Exception):
        r.observed = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# run_placebo_bootstrap
# ---------------------------------------------------------------------------


def test_run_placebo_bootstrap_deterministic_with_seed() -> None:
    def deterministic_metric(sub_seed: int) -> float:
        return float(sub_seed % 7)

    r1 = run_placebo_bootstrap(
        observed_metric=5.0,
        n_replicates=20,
        seed=100,
        placebo_metric_fn=deterministic_metric,
    )
    r2 = run_placebo_bootstrap(
        observed_metric=5.0,
        n_replicates=20,
        seed=100,
        placebo_metric_fn=deterministic_metric,
    )
    assert r1.placebo_values == r2.placebo_values
    assert r1.p_value.two_sided == r2.p_value.two_sided


def test_run_placebo_bootstrap_records_none_as_nan() -> None:
    def metric_that_fails(sub_seed: int):
        if sub_seed % 2 == 0:
            return None
        return 1.0

    r = run_placebo_bootstrap(
        observed_metric=2.0,
        n_replicates=10,
        seed=0,
        placebo_metric_fn=metric_that_fails,
    )
    nan_count = sum(1 for v in r.placebo_values if math.isnan(v))
    finite_count = sum(1 for v in r.placebo_values if math.isfinite(v))
    assert nan_count == 5
    assert finite_count == 5
    assert r.p_value.n_placebos == 5


def test_run_placebo_bootstrap_swallows_metric_exceptions() -> None:
    def metric_that_raises(sub_seed: int) -> float:
        if sub_seed % 3 == 0:
            raise RuntimeError("boom")
        return 1.0

    r = run_placebo_bootstrap(
        observed_metric=2.0,
        n_replicates=9,
        seed=0,
        placebo_metric_fn=metric_that_raises,
    )
    assert isinstance(r, PlaceboBootstrapResult)
    assert len(r.placebo_values) == 9
    nan_count = sum(1 for v in r.placebo_values if math.isnan(v))
    assert nan_count >= 1


def test_run_placebo_bootstrap_rejects_non_positive_replicates() -> None:
    with pytest.raises(ValueError):
        run_placebo_bootstrap(
            observed_metric=1.0,
            n_replicates=0,
            seed=1,
            placebo_metric_fn=lambda s: 1.0,
        )


def test_run_placebo_bootstrap_rejects_non_callable_fn() -> None:
    with pytest.raises(TypeError):
        run_placebo_bootstrap(
            observed_metric=1.0,
            n_replicates=10,
            seed=1,
            placebo_metric_fn="not-callable",  # type: ignore[arg-type]
        )
