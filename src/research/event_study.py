"""Symmetric / asymmetric window event studies on OHLC candles.

What is an event study?
-----------------------
An event study quantifies the *abnormal* behaviour of a price series
around a set of discrete events (Fear & Greed crossings, exchange
status incidents, options expiries, attention spikes, …). For each
event we crop a window of candles around the anchor and compute one
or more metrics — typically forward return, realised volatility,
volume ratio, max drawdown. The aggregated distribution (mean,
median, quantiles, sign-rate, simple t-statistic) is then compared
against a baseline computed on the same dataset, and against placebo
distributions (see :mod:`src.research.placebo`).

This module is the *raw engine*. It does not know what a "good"
result is — that judgement is the caller's job and is documented in
``docs/METHODOLOGY.md`` (the anti-overfitting checklist).

Hard contract
-------------
- **Stdlib only.** The whole module relies on :mod:`math` and
  :mod:`statistics`. No pandas / numpy. This is the same rule as
  :mod:`src.external_signals`, motivated by the small dependency
  footprint of the live trading container.
- **No network I/O, no order placement.** This module never imports
  :mod:`src.execution`, :mod:`src.futures_kraken_cli`,
  :mod:`src.risk`, :mod:`src.kraken_cli` or any module that can
  mutate venue state.
- **Deterministic.** Every helper here is a pure function. Same
  inputs → same outputs. The randomised harness lives in
  :mod:`src.research.placebo` and takes an explicit seed.

Conventions
-----------
- Candles are sequences of mappings exposing at minimum the keys
  ``timestamp`` (int, unix seconds, UTC), ``open``, ``high``,
  ``low``, ``close`` and ``volume`` (floats). This matches both
  :class:`src.kraken_ohlc_paginated.OHLCRow` and
  :func:`src.market_data.get_ohlc`. Extra keys are ignored.
- Events are an iterable of ints (unix seconds, UTC). Non-monotonic
  inputs are accepted; events are anchored individually and the
  output preserves the original order via :class:`EventAnchor`.
- Windows are expressed in **candle counts** relative to the
  anchor candle (``offset == 0``). Asymmetric windows are
  first-class: ``EventStudyWindow("post_3d", 1, 18)`` on 4-hour
  candles covers the 18 candles strictly after the event.
"""

from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from ..logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventStudyWindow:
    """An inclusive ``[start_offset, end_offset]`` range of candle indices.

    Offsets are signed integers measured in **candle counts** relative
    to the anchor candle (``offset == 0``). Negative offsets address
    the past; positive offsets address the future.

    Examples (4-hour candles)
    -------------------------
    ``EventStudyWindow("pre_24h", -6, -1)``      → six candles before the event
    ``EventStudyWindow("event_4h", 0, 0)``       → the anchor candle alone
    ``EventStudyWindow("post_24h", 1, 6)``       → six candles after the event
    ``EventStudyWindow("around_24h", -6, 6)``    → ± one day window
    """

    label: str
    start_offset: int
    end_offset: int

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("EventStudyWindow.label must be a non-empty str")
        if not isinstance(self.start_offset, int) or not isinstance(
            self.end_offset, int
        ):
            raise TypeError(
                "EventStudyWindow offsets must be int, got "
                f"{type(self.start_offset).__name__} / "
                f"{type(self.end_offset).__name__}"
            )
        if self.end_offset < self.start_offset:
            raise ValueError(
                f"EventStudyWindow '{self.label}': end_offset "
                f"({self.end_offset}) < start_offset ({self.start_offset})"
            )

    @property
    def length(self) -> int:
        return self.end_offset - self.start_offset + 1


@dataclass(frozen=True)
class EventAnchor:
    """Resolved anchor for one event.

    ``candle_index`` is the index of the first candle whose
    ``timestamp >= event_timestamp`` (forward as-of join: the event
    cannot influence a candle that closed before it).

    ``in_bounds`` is False when *any* configured window would require
    candles outside the dataset for this anchor. Such events are not
    dropped — they are surfaced in the result so the caller can audit
    truncation behaviour (and decide to widen the cache).
    """

    event_timestamp: int
    candle_index: Optional[int]
    in_bounds: bool


@dataclass(frozen=True)
class EventStudyRow:
    """Aggregated statistics for one ``(metric, window)`` cell."""

    metric: str
    window_label: str
    n_events: int
    n_positive: int
    mean: float
    median: float
    std: float
    q25: float
    q75: float
    t_stat: Optional[float]
    p_value_approx: Optional[float]

    @property
    def hit_rate(self) -> float:
        """Fraction of events with a strictly positive metric value."""
        if self.n_events <= 0:
            return 0.0
        return self.n_positive / self.n_events


@dataclass(frozen=True)
class EventStudyResult:
    """Top-level event study container."""

    events_count: int
    events_used: int
    events_skipped_oob: int
    candles_count: int
    windows: tuple[EventStudyWindow, ...]
    metrics: tuple[str, ...]
    rows: tuple[EventStudyRow, ...]
    baseline: Mapping[str, float] = field(default_factory=dict)

    def row(self, metric: str, window_label: str) -> Optional[EventStudyRow]:
        """Lookup helper. Returns ``None`` when the cell is not present."""
        for r in self.rows:
            if r.metric == metric and r.window_label == window_label:
                return r
        return None


# ---------------------------------------------------------------------------
# Metric callables
# ---------------------------------------------------------------------------


MetricFn = Callable[[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]], Optional[float]]
"""Signature: ``(window_candles, baseline_lookback_candles) -> value | None``.

``window_candles`` is the slice of the OHLC series corresponding to
the event window (always at least one candle). ``baseline_lookback``
is a slice of candles strictly *before* the window — used by metrics
like ``volume_ratio`` that need a pre-event reference. Both slices
are passed as plain :class:`list` slices (not copies of the parent
sequence). A metric MAY return ``None`` to signal "not computable"
(e.g. baseline_lookback is empty); ``None`` results are excluded
from the aggregation but reported through ``EventStudyRow.n_events``.
"""


def metric_simple_return(
    window: Sequence[Mapping[str, Any]],
    baseline_lookback: Sequence[Mapping[str, Any]],  # noqa: ARG001
) -> Optional[float]:
    """Arithmetic return ``(close_last - close_first) / close_first``.

    Computed on the window itself: the close at the *first* candle of
    the window is the entry reference and the close of the *last*
    candle is the exit. Returns ``None`` when the first close is
    non-positive (defensive — never observed on Kraken OHLC but the
    parser would not catch it either).
    """
    if not window:
        return None
    first = _close(window[0])
    last = _close(window[-1])
    if first is None or last is None or first <= 0:
        return None
    return (last - first) / first


def metric_log_return(
    window: Sequence[Mapping[str, Any]],
    baseline_lookback: Sequence[Mapping[str, Any]],  # noqa: ARG001
) -> Optional[float]:
    """``log(close_last / close_first)``. ``None`` when either close <= 0."""
    if not window:
        return None
    first = _close(window[0])
    last = _close(window[-1])
    if first is None or last is None or first <= 0 or last <= 0:
        return None
    return math.log(last / first)


def metric_realized_vol(
    window: Sequence[Mapping[str, Any]],
    baseline_lookback: Sequence[Mapping[str, Any]],  # noqa: ARG001
) -> Optional[float]:
    """Sample stdev of the within-window log returns. ``None`` when n<2."""
    closes = [c for c in (_close(r) for r in window) if c is not None and c > 0]
    if len(closes) < 2:
        return None
    rets: list[float] = []
    for i in range(1, len(closes)):
        rets.append(math.log(closes[i] / closes[i - 1]))
    if len(rets) < 2:
        return None
    try:
        return float(statistics.stdev(rets))
    except statistics.StatisticsError:
        return None


def metric_volume_ratio(
    window: Sequence[Mapping[str, Any]],
    baseline_lookback: Sequence[Mapping[str, Any]],
) -> Optional[float]:
    """``mean(window.volume) / mean(baseline_lookback.volume)``.

    Returns ``None`` when either slice is empty or the baseline mean
    is non-positive — this is *not* uncommon on illiquid pairs and we
    refuse to fake the metric with a tiny epsilon.
    """
    win_vols = [_volume(r) for r in window]
    win_vols = [v for v in win_vols if v is not None and v >= 0]
    base_vols = [_volume(r) for r in baseline_lookback]
    base_vols = [v for v in base_vols if v is not None and v >= 0]
    if not win_vols or not base_vols:
        return None
    win_mean = sum(win_vols) / len(win_vols)
    base_mean = sum(base_vols) / len(base_vols)
    if base_mean <= 0:
        return None
    return win_mean / base_mean


def metric_max_drawdown(
    window: Sequence[Mapping[str, Any]],
    baseline_lookback: Sequence[Mapping[str, Any]],  # noqa: ARG001
) -> Optional[float]:
    """Most negative running drawdown observed within the window.

    Defined on closes only (intra-bar wicks are ignored on purpose:
    we never know how the within-bar path looked, and using highs/lows
    would bias the metric toward more negative values than a strategy
    could actually realise). Always ``<= 0``. ``None`` when the
    window is empty or every close is non-positive.
    """
    closes = [c for c in (_close(r) for r in window) if c is not None and c > 0]
    if not closes:
        return None
    peak = closes[0]
    max_dd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        if peak > 0:
            dd = (c - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return max_dd


METRIC_REGISTRY: dict[str, MetricFn] = {
    "return": metric_simple_return,
    "log_return": metric_log_return,
    "realized_vol": metric_realized_vol,
    "volume_ratio": metric_volume_ratio,
    "max_drawdown": metric_max_drawdown,
}


def register_metric(name: str, fn: MetricFn) -> None:
    """Register a custom metric. Overwrites any existing entry with the same name.

    Mostly useful from research notebooks / scripts that need a
    one-off metric — the canonical built-ins above cover the vast
    majority of cases. Custom metrics must respect :data:`MetricFn`.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("metric name must be a non-empty str")
    if not callable(fn):
        raise TypeError("metric fn must be callable")
    METRIC_REGISTRY[name] = fn


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _close(row: Mapping[str, Any]) -> Optional[float]:
    if not isinstance(row, Mapping):
        return None
    val = row.get("close")
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _volume(row: Mapping[str, Any]) -> Optional[float]:
    if not isinstance(row, Mapping):
        return None
    val = row.get("volume")
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _timestamp(row: Mapping[str, Any]) -> Optional[int]:
    if not isinstance(row, Mapping):
        return None
    val = row.get("timestamp")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _normalize_candles(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Drop rows with no timestamp / no close, sort by timestamp asc.

    The Kraken CLI already returns timestamp-ascending OHLC, but a
    user-built list may not. Sorting once up-front lets the rest of
    the module assume monotonic input.
    """
    cleaned: list[Mapping[str, Any]] = []
    for row in rows:
        ts = _timestamp(row)
        cl = _close(row)
        if ts is None or cl is None:
            continue
        cleaned.append(row)
    cleaned.sort(key=lambda r: int(r["timestamp"]))
    return cleaned


def _aligned_indices(
    candles: Sequence[Mapping[str, Any]],
    events: Iterable[int],
) -> list[Optional[int]]:
    """Forward as-of: ``candles[i].timestamp >= event_timestamp``.

    Returns ``None`` for events that fall strictly after the last
    candle (we cannot anchor them) — the caller surfaces them via
    :attr:`EventStudyResult.events_skipped_oob`.
    """
    if not candles:
        return [None for _ in events]
    timestamps = [int(c["timestamp"]) for c in candles]
    out: list[Optional[int]] = []
    for ev in events:
        try:
            ev_int = int(ev)
        except (TypeError, ValueError):
            out.append(None)
            continue
        idx = bisect.bisect_left(timestamps, ev_int)
        if idx >= len(timestamps):
            out.append(None)
        else:
            out.append(idx)
    return out


def _safe_quantiles(values: Sequence[float]) -> tuple[float, float, float]:
    """Return ``(q25, median, q75)`` with linear interpolation.

    Falls back to the sole sample when ``len(values) == 1``; returns
    zeros for an empty input so the caller's row is always
    well-formed (the row will already report ``n_events == 0``).
    """
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0
    if n == 1:
        v = float(values[0])
        return v, v, v
    sorted_vals = sorted(float(v) for v in values)

    def _q(p: float) -> float:
        idx = (n - 1) * p
        lo = int(math.floor(idx))
        hi = min(lo + 1, n - 1)
        weight = idx - lo
        return sorted_vals[lo] * (1.0 - weight) + sorted_vals[hi] * weight

    return _q(0.25), _q(0.5), _q(0.75)


def _erf(x: float) -> float:
    """Numerically stable :func:`math.erf` wrapper.

    :func:`math.erf` already handles the full range; this thin wrapper
    exists so the t→p approximation reads cleanly below.
    """
    return math.erf(x)


def _approx_two_sided_p(t_stat: float, df: int) -> Optional[float]:
    """Crude two-sided p-value approximation for a one-sample t statistic.

    Uses the standard normal approximation, valid for ``df`` of a few
    dozen or more. We deliberately *do not* import :mod:`scipy.stats`
    just to compute an exact value — research code should treat this
    as a quick triage indicator rather than a publication-grade test,
    and pair it with the placebo distribution in
    :mod:`src.research.placebo`.

    Returns ``None`` when ``df < 2`` (no variance estimate) or the
    statistic is not finite.
    """
    if df < 2:
        return None
    if not math.isfinite(t_stat):
        return None
    z = abs(t_stat)
    p = 1.0 - 0.5 * (1.0 + _erf(z / math.sqrt(2.0)))
    return max(0.0, min(1.0, 2.0 * p))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_event_study(
    candles: Sequence[Mapping[str, Any]],
    events: Iterable[int],
    windows: Sequence[EventStudyWindow],
    metrics: Sequence[str | tuple[str, MetricFn]] = ("return", "realized_vol"),
    *,
    baseline_lookback_candles: int = 30,
    compute_baseline: bool = True,
) -> EventStudyResult:
    """Run an event study and return aggregated statistics per ``(metric, window)``.

    Parameters
    ----------
    candles:
        OHLC sequence (see module docstring for the expected keys).
        Will be normalised (dropna, sort by timestamp ascending)
        before processing.
    events:
        Iterable of unix timestamps (UTC seconds). Non-int entries
        are silently skipped.
    windows:
        Sequence of :class:`EventStudyWindow`. At least one is
        required. Asymmetric windows are first-class.
    metrics:
        Sequence of metric specifications. Each item is either:

        - a string referencing :data:`METRIC_REGISTRY` (one of
          ``"return" | "log_return" | "realized_vol" |
          "volume_ratio" | "max_drawdown"``), or
        - a ``(name, fn)`` tuple to register / override a metric
          inline. The name is what shows up in the result rows.

        Default: ``("return", "realized_vol")`` — the cheapest pair
        that already differentiates "direction-bearing" from
        "vol-bearing" signals.
    baseline_lookback_candles:
        Number of candles strictly before the window's first candle
        to expose to volume-ratio-style metrics. Ignored by metrics
        that do not consume it. Default 30 (≈ 5 days of 4-hour bars).
    compute_baseline:
        When True, also compute the global mean of each metric on
        sliding windows of the same shape — gives the caller an
        immediate "is the post-event mean above or below the
        unconditional mean?" check. Default True.

    Returns
    -------
    EventStudyResult
        Full result, including out-of-bounds skip count and per-cell
        statistics.

    Raises
    ------
    ValueError
        If ``windows`` is empty or ``metrics`` is empty.
    KeyError
        If a metric name does not resolve in :data:`METRIC_REGISTRY`.
    """
    if not windows:
        raise ValueError("at least one EventStudyWindow is required")
    if not metrics:
        raise ValueError("at least one metric is required")
    if baseline_lookback_candles < 0:
        raise ValueError(
            f"baseline_lookback_candles must be >= 0 (got {baseline_lookback_candles})"
        )

    metric_specs: list[tuple[str, MetricFn]] = []
    for m in metrics:
        if isinstance(m, str):
            if m not in METRIC_REGISTRY:
                raise KeyError(
                    f"unknown metric {m!r}; known: {sorted(METRIC_REGISTRY)}"
                )
            metric_specs.append((m, METRIC_REGISTRY[m]))
        elif isinstance(m, tuple) and len(m) == 2 and callable(m[1]):
            metric_specs.append((str(m[0]), m[1]))
        else:
            raise TypeError(
                f"metric spec must be a str or (name, callable) tuple, got {m!r}"
            )

    norm_candles = _normalize_candles(candles)
    n_candles = len(norm_candles)
    events_list = list(events)
    anchor_indices = _aligned_indices(norm_candles, events_list)

    events_used = 0
    events_skipped_oob = 0
    cell_values: dict[tuple[str, str], list[float]] = {
        (m, w.label): [] for w in windows for m, _ in metric_specs
    }

    for anchor_idx in anchor_indices:
        if anchor_idx is None:
            events_skipped_oob += 1
            continue
        any_in_bounds = False
        for window in windows:
            start = anchor_idx + window.start_offset
            end = anchor_idx + window.end_offset
            if start < 0 or end >= n_candles:
                continue
            any_in_bounds = True
            win_slice = norm_candles[start : end + 1]
            base_start = max(0, start - baseline_lookback_candles)
            base_slice = norm_candles[base_start:start]
            for metric_name, metric_fn in metric_specs:
                try:
                    val = metric_fn(win_slice, base_slice)
                except Exception as exc:  # pragma: no cover (defensive)
                    logger.warning(
                        "metric %r raised on window %r: %s",
                        metric_name, window.label, exc,
                    )
                    val = None
                if val is None or not math.isfinite(float(val)):
                    continue
                cell_values[(metric_name, window.label)].append(float(val))
        if any_in_bounds:
            events_used += 1
        else:
            events_skipped_oob += 1

    rows: list[EventStudyRow] = []
    for metric_name, _ in metric_specs:
        for window in windows:
            values = cell_values[(metric_name, window.label)]
            n = len(values)
            if n == 0:
                rows.append(
                    EventStudyRow(
                        metric=metric_name,
                        window_label=window.label,
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
                )
                continue
            mean = sum(values) / n
            if n >= 2:
                std = float(statistics.stdev(values))
            else:
                std = 0.0
            q25, median, q75 = _safe_quantiles(values)
            n_positive = sum(1 for v in values if v > 0)
            t_stat: Optional[float] = None
            p_val: Optional[float] = None
            if n >= 2 and std > 0:
                t_stat = mean / (std / math.sqrt(n))
                p_val = _approx_two_sided_p(t_stat, df=n - 1)
            rows.append(
                EventStudyRow(
                    metric=metric_name,
                    window_label=window.label,
                    n_events=n,
                    n_positive=n_positive,
                    mean=mean,
                    median=median,
                    std=std,
                    q25=q25,
                    q75=q75,
                    t_stat=t_stat,
                    p_value_approx=p_val,
                )
            )

    baseline: dict[str, float] = {}
    if compute_baseline and norm_candles:
        baseline = _compute_baseline(norm_candles, windows, metric_specs, baseline_lookback_candles)

    return EventStudyResult(
        events_count=len(events_list),
        events_used=events_used,
        events_skipped_oob=events_skipped_oob,
        candles_count=n_candles,
        windows=tuple(windows),
        metrics=tuple(m for m, _ in metric_specs),
        rows=tuple(rows),
        baseline=baseline,
    )


def _compute_baseline(
    candles: Sequence[Mapping[str, Any]],
    windows: Sequence[EventStudyWindow],
    metric_specs: Sequence[tuple[str, MetricFn]],
    baseline_lookback_candles: int,
) -> dict[str, float]:
    """Mean of each metric over all admissible sliding placements.

    Uses the *first* window's shape as the canonical reference (most
    callers pass a single "post-event" window for direction studies
    and the result is unambiguous; multi-window callers should
    interpret the baseline as "metric mean under random anchoring",
    not as window-specific). Each anchor index ``i`` such that
    ``i + start_offset >= 0`` and ``i + end_offset < len(candles)``
    contributes one observation.
    """
    if not windows:
        return {}
    window = windows[0]
    out: dict[str, float] = {}
    n_candles = len(candles)
    for metric_name, metric_fn in metric_specs:
        values: list[float] = []
        for i in range(n_candles):
            start = i + window.start_offset
            end = i + window.end_offset
            if start < 0 or end >= n_candles:
                continue
            win_slice = candles[start : end + 1]
            base_start = max(0, start - baseline_lookback_candles)
            base_slice = candles[base_start:start]
            try:
                v = metric_fn(win_slice, base_slice)
            except Exception:  # pragma: no cover
                continue
            if v is None or not math.isfinite(float(v)):
                continue
            values.append(float(v))
        if values:
            out[metric_name] = sum(values) / len(values)
    return out


# ---------------------------------------------------------------------------
# Convenience factories
# ---------------------------------------------------------------------------


def make_symmetric_windows(
    label_prefix: str,
    offsets: Sequence[int],
) -> tuple[EventStudyWindow, ...]:
    """Build a series of single-candle pre/post windows.

    Example
    -------
    ``make_symmetric_windows("h", [-24, -6, -1, 1, 6, 24])`` on hourly
    candles returns six 1-candle windows labelled ``"h-24"``,
    ``"h-6"``, …, ``"h+24"``. Useful for "snapshot" event studies
    where the caller wants the metric *at* each offset rather than a
    range.
    """
    out: list[EventStudyWindow] = []
    for off in offsets:
        if not isinstance(off, int):
            raise TypeError(f"offset must be int, got {type(off).__name__}")
        sign = "+" if off > 0 else ""
        out.append(EventStudyWindow(f"{label_prefix}{sign}{off}", off, off))
    return tuple(out)


def make_post_event_windows(
    label_prefix: str,
    horizons: Sequence[int],
) -> tuple[EventStudyWindow, ...]:
    """Build cumulative post-event windows ``[1, h]`` for each ``h`` in horizons.

    Example
    -------
    ``make_post_event_windows("post", [6, 24, 72])`` returns three
    windows: ``post_6`` covering candles 1..6, ``post_24`` covering
    1..24, ``post_72`` covering 1..72. The 0-th candle (the anchor)
    is excluded because it usually overlaps with the event itself —
    callers wanting to include it should pass an explicit
    :class:`EventStudyWindow`.
    """
    out: list[EventStudyWindow] = []
    for h in horizons:
        if not isinstance(h, int) or h < 1:
            raise ValueError(f"horizon must be a positive int, got {h!r}")
        out.append(EventStudyWindow(f"{label_prefix}_{h}", 1, h))
    return tuple(out)


__all__ = [
    "EventStudyWindow",
    "EventAnchor",
    "EventStudyRow",
    "EventStudyResult",
    "MetricFn",
    "METRIC_REGISTRY",
    "register_metric",
    "metric_simple_return",
    "metric_log_return",
    "metric_realized_vol",
    "metric_volume_ratio",
    "metric_max_drawdown",
    "make_symmetric_windows",
    "make_post_event_windows",
    "run_event_study",
]
