"""Placebo / falsification harness for event studies.

What this module is for
-----------------------
An event-study mean that looks impressive in isolation is meaningless
until you have shown the *same* methodology produces uninteresting
results on (a) the same dataset with the events shuffled or shifted,
and (b) random events drawn from the same time index. This module
implements the three standard placebos plus the two multiple-testing
corrections we routinely need when sweeping many hypotheses at once.

Three placebo strategies are implemented:

1. :func:`shift_events_in_time` — translates every event by a fixed
   number of seconds (often ``+ 30 days`` or ``- 30 days``). The
   true signal should *not* survive this manipulation. Use this when
   the original events come from a feed timestamped against the
   market (Fear & Greed crossings, exchange status incidents,
   options expiries …).
2. :func:`random_events_from_candles` — draws ``n`` event timestamps
   uniformly at random from the candle index. The expected metric
   distribution under the null is centred on the global baseline,
   and the real-event metric should differ from it by more than the
   placebo sampling error. Use this when you cannot timestamp-shift
   (e.g. calendar-based events like FOMC).
3. :func:`shuffle_labels` — Fisher-Yates shuffle of a metric series
   while preserving the event anchors. Use this when the events are
   tied to a *labelled* output (e.g. you already computed per-event
   forward returns and want to test "would I see this mean by
   chance if I assigned each return to a random event?").

On top of the placebos we expose:

- :func:`bonferroni_threshold` — the simplest multi-test correction.
  Conservative; use when you ran k independent tests and need a
  no-questions-asked answer.
- :func:`benjamini_hochberg` — controls the False Discovery Rate;
  much less conservative than Bonferroni when many tests are
  expected to be significant. Returns the BH-adjusted q-values and
  the boolean acceptance mask.
- :func:`empirical_p_value` — given an observed real metric value and
  a vector of placebo values produced by repeated runs of one of the
  placebo helpers, returns a two-sided percentile-rank p-value.
  This is the *recommended* way to interpret an event-study result:
  pair the real run with N=500 placebo runs, then compare.

Hard contract
-------------
- Stdlib only. Same constraint as :mod:`src.research.event_study`.
- Deterministic given an explicit seed. Every randomised helper
  takes a ``seed`` argument and uses a *local* :class:`random.Random`
  instance — never the module-level RNG — so concurrent callers do
  not perturb each other.
- No network I/O. No order placement. No imports of
  :mod:`src.execution`, :mod:`src.futures_kraken_cli`, :mod:`src.risk`
  or any other live-trading module.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from ..logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Event-level placebos
# ---------------------------------------------------------------------------


def shift_events_in_time(
    events: Iterable[int],
    *,
    delta_seconds: int,
) -> list[int]:
    """Translate every event timestamp by ``delta_seconds``.

    The cardinality is preserved and the order is preserved. Non-int
    inputs are silently dropped — this matches the parser hygiene of
    :func:`src.research.event_study.run_event_study`.

    A ``delta_seconds`` of ``86_400 * 30`` (= +30 days) is the
    canonical placebo for daily / weekly feeds where the events are
    "real but their timestamps are meaningless if you displace them
    by a month".
    """
    if not isinstance(delta_seconds, int):
        raise TypeError(
            f"delta_seconds must be int, got {type(delta_seconds).__name__}"
        )
    out: list[int] = []
    for ev in events:
        try:
            out.append(int(ev) + delta_seconds)
        except (TypeError, ValueError):
            continue
    return out


def random_events_from_candles(
    candle_timestamps: Sequence[int],
    n_events: int,
    *,
    seed: int,
    allow_duplicates: bool = False,
) -> list[int]:
    """Draw ``n_events`` event timestamps uniformly from ``candle_timestamps``.

    Parameters
    ----------
    candle_timestamps:
        Sequence of candidate unix timestamps. Typically
        ``[c["timestamp"] for c in normalized_candles]``.
    n_events:
        Number of placebo events to draw. Must be ``>= 0``. When
        ``allow_duplicates`` is False, must also be
        ``<= len(candle_timestamps)``.
    seed:
        Required. Pinning the seed is non-negotiable for
        reproducibility — random placebos that change between runs
        are useless for forensics.
    allow_duplicates:
        If True, samples with replacement (a single timestamp can be
        picked multiple times). Default False (i.e. ``random.sample``
        semantics).

    Returns
    -------
    list[int]
        ``n_events`` timestamps, **sorted ascending** so the result
        plugs straight into :func:`run_event_study`.
    """
    if not isinstance(n_events, int) or n_events < 0:
        raise ValueError(f"n_events must be a non-negative int, got {n_events!r}")
    pool = [int(t) for t in candle_timestamps]
    if n_events == 0 or not pool:
        return []
    rng = random.Random(int(seed))
    if allow_duplicates:
        picks = [rng.choice(pool) for _ in range(n_events)]
    else:
        if n_events > len(pool):
            raise ValueError(
                f"n_events ({n_events}) > pool size ({len(pool)}) and "
                "allow_duplicates is False"
            )
        picks = rng.sample(pool, n_events)
    picks.sort()
    return picks


def shuffle_labels(values: Sequence[float], *, seed: int) -> list[float]:
    """Fisher–Yates shuffle of a per-event metric series.

    The returned list is a new list (input is not mutated). Use it
    to test "would the same mean appear by chance under a random
    matching of events to outcomes?".
    """
    if not isinstance(seed, int):
        raise TypeError(f"seed must be int, got {type(seed).__name__}")
    out = [float(v) for v in values]
    rng = random.Random(int(seed))
    rng.shuffle(out)
    return out


# ---------------------------------------------------------------------------
# Multiple-testing corrections
# ---------------------------------------------------------------------------


def bonferroni_threshold(alpha: float, n_tests: int) -> float:
    """Return the Bonferroni-corrected per-test alpha.

    Formula: ``alpha / n_tests``. Reject ``H0`` when ``p < this``.

    Note
    ----
    Bonferroni is conservative; with hundreds of correlated tests it
    will accept essentially nothing. For exploratory screening prefer
    :func:`benjamini_hochberg`, then Bonferroni only as a sanity
    check on the very small remaining shortlist.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    if not isinstance(n_tests, int) or n_tests <= 0:
        raise ValueError(f"n_tests must be a positive int, got {n_tests!r}")
    return alpha / n_tests


@dataclass(frozen=True)
class BenjaminiHochbergResult:
    """Output of the BH False-Discovery-Rate correction.

    Attributes
    ----------
    alpha:
        The target FDR level passed in.
    p_values:
        The input p-values, in the **original** order.
    q_values:
        BH-adjusted q-values, in the same order as ``p_values``.
        The convention is the standard Benjamini–Hochberg adjusted
        p: ``q_i = min(p_{(j)} * m / j for all j >= i)`` mapped back
        to the input order.
    rejected:
        Boolean mask aligned with ``p_values``. True means the
        corresponding null is rejected (the test is "significant"
        under BH at the requested FDR level).
    n_rejected:
        Number of ``True`` entries in ``rejected``. Equivalent to
        ``sum(rejected)`` but exposed for convenience.
    """

    alpha: float
    p_values: tuple[float, ...]
    q_values: tuple[float, ...]
    rejected: tuple[bool, ...]
    n_rejected: int


def benjamini_hochberg(
    p_values: Sequence[float],
    alpha: float = 0.05,
) -> BenjaminiHochbergResult:
    """Benjamini–Hochberg FDR control on a vector of p-values.

    The standard procedure:

    1. Sort the m p-values ascending: ``p_(1) <= p_(2) <= … <= p_(m)``.
    2. Find the largest ``k`` such that ``p_(k) <= k/m * alpha``.
    3. Reject ``H_(1) … H_(k)`` (the k smallest-p tests).

    Adjusted q-values (the BH-adjusted p analogue) are computed in
    the standard "step-up" form and clipped to ``[0, 1]``.

    Parameters
    ----------
    p_values:
        Sequence of p-values in ``[0, 1]``. ``None`` is rejected. NaN
        entries cause a ValueError so the caller is forced to handle
        the missingness explicitly.
    alpha:
        Target False Discovery Rate. Default 0.05.

    Returns
    -------
    BenjaminiHochbergResult
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    p_list: list[float] = []
    for i, p in enumerate(p_values):
        if p is None:
            raise ValueError(f"p_values[{i}] is None")
        pf = float(p)
        if not math.isfinite(pf):
            raise ValueError(f"p_values[{i}] is not finite: {pf}")
        if pf < 0.0 or pf > 1.0:
            raise ValueError(f"p_values[{i}] = {pf} outside [0, 1]")
        p_list.append(pf)
    m = len(p_list)
    if m == 0:
        return BenjaminiHochbergResult(
            alpha=alpha,
            p_values=(),
            q_values=(),
            rejected=(),
            n_rejected=0,
        )

    indexed = sorted(enumerate(p_list), key=lambda x: x[1])
    sorted_p = [v for _, v in indexed]
    original_indices = [i for i, _ in indexed]

    q_sorted = [0.0] * m
    running_min = 1.0
    for k in range(m, 0, -1):
        adj = sorted_p[k - 1] * m / k
        if adj < running_min:
            running_min = adj
        q_sorted[k - 1] = min(running_min, 1.0)

    q_values = [0.0] * m
    for sorted_pos, orig_idx in enumerate(original_indices):
        q_values[orig_idx] = q_sorted[sorted_pos]

    k_star = 0
    for k in range(1, m + 1):
        if sorted_p[k - 1] <= k / m * alpha:
            k_star = k

    rejected_sorted_flag = [False] * m
    for j in range(k_star):
        rejected_sorted_flag[j] = True

    rejected = [False] * m
    for sorted_pos, orig_idx in enumerate(original_indices):
        rejected[orig_idx] = rejected_sorted_flag[sorted_pos]

    return BenjaminiHochbergResult(
        alpha=alpha,
        p_values=tuple(p_list),
        q_values=tuple(q_values),
        rejected=tuple(rejected),
        n_rejected=sum(rejected),
    )


# ---------------------------------------------------------------------------
# Empirical p-value from a placebo bootstrap
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmpiricalPValueResult:
    """Output of :func:`empirical_p_value`.

    Attributes
    ----------
    observed:
        The real-event metric value.
    n_placebos:
        Number of placebo metric values used as the null distribution.
    one_sided_greater:
        ``(1 + #{p >= observed}) / (1 + n_placebos)``. Use when the
        alternative hypothesis is "real is *greater than* the null".
    one_sided_less:
        Symmetric counterpart.
    two_sided:
        ``2 * min(one_sided_greater, one_sided_less)``, capped at 1.
        Use when the alternative is "real *differs from* the null".
    percentile_rank:
        Where the observed value sits within the placebo distribution,
        in ``[0, 100]``. 50 = at the median of the null; 99 = above
        99 % of placebos.
    """

    observed: float
    n_placebos: int
    one_sided_greater: float
    one_sided_less: float
    two_sided: float
    percentile_rank: float


def empirical_p_value(
    observed: float,
    placebo_values: Sequence[float],
) -> EmpiricalPValueResult:
    """Compare an observed metric to a placebo distribution.

    The classic "+1 / +1" smoothing avoids the degenerate ``p == 0``
    output when the observed value happens to be the most extreme
    sample, which would be a misleading certificate of significance.

    Parameters
    ----------
    observed:
        The real-event metric value (e.g. ``event_study_result
        .row("return", "post_24h").mean``).
    placebo_values:
        Sequence of metric values produced by the placebo bootstrap.
        Must be non-empty; non-finite entries are dropped silently
        (a placebo that failed to compute is just a missing sample,
        not a poison pill).

    Returns
    -------
    EmpiricalPValueResult
    """
    if not math.isfinite(float(observed)):
        raise ValueError(f"observed must be finite, got {observed!r}")
    cleaned = [float(v) for v in placebo_values if v is not None and math.isfinite(float(v))]
    n = len(cleaned)
    if n == 0:
        raise ValueError("placebo_values is empty after dropping non-finite entries")
    obs = float(observed)
    n_ge = sum(1 for v in cleaned if v >= obs)
    n_le = sum(1 for v in cleaned if v <= obs)
    one_sided_greater = (1 + n_ge) / (1 + n)
    one_sided_less = (1 + n_le) / (1 + n)
    two_sided = min(1.0, 2.0 * min(one_sided_greater, one_sided_less))
    n_strictly_less = sum(1 for v in cleaned if v < obs)
    n_equal = sum(1 for v in cleaned if v == obs)
    rank = n_strictly_less + 0.5 * n_equal
    percentile_rank = (rank / n) * 100.0
    return EmpiricalPValueResult(
        observed=obs,
        n_placebos=n,
        one_sided_greater=one_sided_greater,
        one_sided_less=one_sided_less,
        two_sided=two_sided,
        percentile_rank=percentile_rank,
    )


# ---------------------------------------------------------------------------
# Lightweight bootstrap orchestrator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlaceboBootstrapResult:
    """Output of :func:`run_placebo_bootstrap`.

    Attributes
    ----------
    observed_metric:
        Real metric value the caller produced before the bootstrap.
    placebo_values:
        Per-replicate metric values. Length == ``n_replicates``
        unless some replicates returned ``None``, in which case they
        are recorded as ``math.nan`` so the caller can audit the
        failure rate without losing the per-replicate position.
    p_value:
        :class:`EmpiricalPValueResult` of the comparison.
    seed:
        Echo of the input seed, for forensics.
    """

    observed_metric: float
    placebo_values: tuple[float, ...]
    p_value: EmpiricalPValueResult
    seed: int


def run_placebo_bootstrap(
    *,
    observed_metric: float,
    n_replicates: int,
    seed: int,
    placebo_metric_fn,
) -> PlaceboBootstrapResult:
    """Generic bootstrap loop: call ``placebo_metric_fn`` ``n_replicates`` times.

    Parameters
    ----------
    observed_metric:
        The real-event metric value being challenged.
    n_replicates:
        Number of placebo replicates. 200 is a reasonable minimum;
        500 is the recommended default for publication-quality
        triage in the research notebooks.
    seed:
        Master seed. The bootstrap derives one sub-seed per
        replicate (``master_seed + replicate_index``) so each
        replicate is reproducible in isolation.
    placebo_metric_fn:
        Callable ``(int) -> float | None``: takes the per-replicate
        seed and returns one placebo metric value. ``None`` (or any
        non-finite float) marks a failed replicate and is recorded
        as ``nan``; the empirical p-value computation drops those
        entries.

    Returns
    -------
    PlaceboBootstrapResult
    """
    if not isinstance(n_replicates, int) or n_replicates <= 0:
        raise ValueError(f"n_replicates must be a positive int, got {n_replicates!r}")
    if not callable(placebo_metric_fn):
        raise TypeError("placebo_metric_fn must be callable")

    replicate_values: list[float] = []
    for i in range(n_replicates):
        sub_seed = int(seed) + i
        try:
            val = placebo_metric_fn(sub_seed)
        except Exception as exc:
            logger.warning("placebo replicate %d raised: %s", i, exc)
            replicate_values.append(math.nan)
            continue
        if val is None:
            replicate_values.append(math.nan)
            continue
        try:
            fv = float(val)
        except (TypeError, ValueError):
            replicate_values.append(math.nan)
            continue
        if not math.isfinite(fv):
            replicate_values.append(math.nan)
            continue
        replicate_values.append(fv)

    finite = [v for v in replicate_values if math.isfinite(v)]
    p = empirical_p_value(observed_metric, finite)
    return PlaceboBootstrapResult(
        observed_metric=float(observed_metric),
        placebo_values=tuple(replicate_values),
        p_value=p,
        seed=int(seed),
    )


__all__ = [
    "shift_events_in_time",
    "random_events_from_candles",
    "shuffle_labels",
    "bonferroni_threshold",
    "BenjaminiHochbergResult",
    "benjamini_hochberg",
    "EmpiricalPValueResult",
    "empirical_p_value",
    "PlaceboBootstrapResult",
    "run_placebo_bootstrap",
]
