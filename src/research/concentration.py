"""Concentration-risk diagnostics for event-study and alpha research.

Measures whether an aggregate result (mean return, cumulative PnL proxy,
hit-rate driver, etc.) is **dominated** by a handful of events or calendar
months. High concentration invalidates robustness claims under gate G2
in ``docs/SIGNAL_REJECTION_POLICY.md``.

Hard contract
-------------
- **Stdlib only** — same rule as :mod:`src.research.event_study` and
  :mod:`src.research.placebo`.
- **Deterministic** — pure functions; same inputs → same outputs.
- **No network I/O, no execution imports.**

Thresholds (canonical, used by :func:`classify_concentration_risk`)
--------------------------------------------------------------------
- Single event share **> 20 %** of total absolute contribution → high risk.
- Top **3** events combined **> 50 %** → high risk.
- Single calendar month **> 40 %** → high risk.
- Event count **< min_events** (default 5) → insufficient evidence.

Shares are computed on **absolute** per-event contributions so that
offsetting wins/losses do not mask dominance by one large magnitude.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Canonical policy thresholds (documented in SIGNAL_REJECTION_POLICY.md G2b).
SINGLE_EVENT_HIGH_RISK_SHARE = 0.20
TOP_N_HIGH_RISK_SHARE = 0.50
TOP_N_DEFAULT = 3
MONTH_HIGH_RISK_SHARE = 0.40
DEFAULT_MIN_EVENTS = 5


def _validate_contributions(contributions: Sequence[float]) -> list[float]:
    if not isinstance(contributions, Sequence):
        raise TypeError("contributions must be a sequence")
    out: list[float] = []
    for i, raw in enumerate(contributions):
        if raw is None:
            raise ValueError(f"contributions[{i}] is None")
        try:
            v = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"contributions[{i}] is not numeric: {raw!r}") from exc
        if not math.isfinite(v):
            raise ValueError(f"contributions[{i}] is not finite: {v}")
        out.append(v)
    return out


def _total_abs(contributions: Sequence[float]) -> float:
    return sum(abs(c) for c in contributions)


def _share(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return numerator / denominator


@dataclass(frozen=True)
class MaxSingleEventContribution:
    """Largest single-event share of total absolute contribution."""

    max_share: float
    event_index: int
    contribution: float
    total_abs: float
    high_risk: bool


def max_single_event_contribution(
    contributions: Sequence[float],
    *,
    threshold: float = SINGLE_EVENT_HIGH_RISK_SHARE,
) -> MaxSingleEventContribution:
    """Return the maximum single-event share of ``sum(abs(contributions))``.

    Parameters
    ----------
    contributions:
        Per-event scalar contributions (e.g. forward return, PnL slice).
    threshold:
        Share above which ``high_risk`` is True (default 20 %).
    """
    vals = _validate_contributions(contributions)
    if len(vals) == 0:
        raise ValueError("contributions must not be empty")
    if not 0.0 < threshold < 1.0:
        raise ValueError(f"threshold must be in (0, 1), got {threshold!r}")

    total = _total_abs(vals)
    if total <= 0.0:
        return MaxSingleEventContribution(
            max_share=0.0,
            event_index=-1,
            contribution=0.0,
            total_abs=0.0,
            high_risk=False,
        )

    best_idx = 0
    best_abs = abs(vals[0])
    for i, v in enumerate(vals[1:], start=1):
        a = abs(v)
        if a > best_abs:
            best_abs = a
            best_idx = i
    share = best_abs / total
    return MaxSingleEventContribution(
        max_share=share,
        event_index=best_idx,
        contribution=vals[best_idx],
        total_abs=total,
        high_risk=share > threshold,
    )


@dataclass(frozen=True)
class TopNEventsContribution:
    """Combined share of the top *n* events by absolute contribution."""

    top_n: int
    combined_share: float
    event_indices: tuple[int, ...]
    total_abs: float
    high_risk: bool


def top_n_events_contribution(
    contributions: Sequence[float],
    n: int = TOP_N_DEFAULT,
    *,
    threshold: float = TOP_N_HIGH_RISK_SHARE,
) -> TopNEventsContribution:
    """Sum absolute shares of the *n* largest-magnitude events."""
    vals = _validate_contributions(contributions)
    if len(vals) == 0:
        raise ValueError("contributions must not be empty")
    if not isinstance(n, int) or n <= 0:
        raise ValueError(f"n must be a positive int, got {n!r}")
    if not 0.0 < threshold < 1.0:
        raise ValueError(f"threshold must be in (0, 1), got {threshold!r}")

    total = _total_abs(vals)
    if total <= 0.0:
        return TopNEventsContribution(
            top_n=n,
            combined_share=0.0,
            event_indices=(),
            total_abs=0.0,
            high_risk=False,
        )

    ranked = sorted(
        enumerate(vals),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
    take = ranked[: min(n, len(ranked))]
    top_sum = sum(abs(v) for _, v in take)
    share = top_sum / total
    return TopNEventsContribution(
        top_n=n,
        combined_share=share,
        event_indices=tuple(i for i, _ in take),
        total_abs=total,
        high_risk=share > threshold,
    )


@dataclass(frozen=True)
class MaxMonthContribution:
    """Largest calendar-month share of total absolute contribution."""

    max_share: float
    month: str
    total_abs: float
    high_risk: bool
    month_shares: tuple[tuple[str, float], ...]


def _month_key_from_timestamp(ts: int) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(ts, tz=_dt.UTC).strftime("%Y-%m")


def max_month_contribution(
    contributions: Sequence[float],
    event_months: Sequence[str] | None = None,
    *,
    event_timestamps: Sequence[int] | None = None,
    threshold: float = MONTH_HIGH_RISK_SHARE,
) -> MaxMonthContribution:
    """Group events by ``YYYY-MM`` month and return the dominant month share.

    Provide either ``event_months`` (parallel to ``contributions``) or
    ``event_timestamps`` (unix seconds, UTC) from which months are derived.
    """
    vals = _validate_contributions(contributions)
    if len(vals) == 0:
        raise ValueError("contributions must not be empty")
    if not 0.0 < threshold < 1.0:
        raise ValueError(f"threshold must be in (0, 1), got {threshold!r}")

    if event_months is not None and event_timestamps is not None:
        raise ValueError("provide event_months or event_timestamps, not both")
    if event_months is not None:
        if len(event_months) != len(vals):
            raise ValueError(
                f"event_months length {len(event_months)} != "
                f"contributions length {len(vals)}"
            )
        months = [str(m) for m in event_months]
    elif event_timestamps is not None:
        if len(event_timestamps) != len(vals):
            raise ValueError(
                f"event_timestamps length {len(event_timestamps)} != "
                f"contributions length {len(vals)}"
            )
        months = []
        for i, ts in enumerate(event_timestamps):
            if not isinstance(ts, int):
                raise TypeError(f"event_timestamps[{i}] must be int, got {type(ts)}")
            months.append(_month_key_from_timestamp(ts))
    else:
        raise ValueError("event_months or event_timestamps is required")

    total = _total_abs(vals)
    if total <= 0.0:
        return MaxMonthContribution(
            max_share=0.0,
            month="",
            total_abs=0.0,
            high_risk=False,
            month_shares=(),
        )

    by_month: dict[str, float] = {}
    for month, value in zip(months, vals, strict=True):
        by_month[month] = by_month.get(month, 0.0) + abs(value)

    month_shares = sorted(
        ((m, s / total) for m, s in by_month.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    best_month, best_share = month_shares[0]
    return MaxMonthContribution(
        max_share=best_share,
        month=best_month,
        total_abs=total,
        high_risk=best_share > threshold,
        month_shares=tuple(month_shares),
    )


@dataclass(frozen=True)
class EventCountSufficiency:
    """Whether the sample has enough events for robust inference."""

    n_events: int
    min_events: int
    sufficient: bool


def event_count_sufficiency(
    n_events: int,
    min_events: int = DEFAULT_MIN_EVENTS,
) -> EventCountSufficiency:
    """True when ``n_events >= min_events`` (default 5, aligned with gate G0)."""
    if not isinstance(n_events, int) or n_events < 0:
        raise ValueError(f"n_events must be a non-negative int, got {n_events!r}")
    if not isinstance(min_events, int) or min_events <= 0:
        raise ValueError(f"min_events must be a positive int, got {min_events!r}")
    return EventCountSufficiency(
        n_events=n_events,
        min_events=min_events,
        sufficient=n_events >= min_events,
    )


@dataclass(frozen=True)
class ConcentrationRiskClassification:
    """Aggregate concentration verdict for gate G2."""

    verdict: str
    insufficient_evidence: bool
    single_event_high_risk: bool
    top_n_high_risk: bool
    month_high_risk: bool
    max_single: MaxSingleEventContribution
    top_n: TopNEventsContribution
    max_month: MaxMonthContribution
    event_count: EventCountSufficiency
    reasons: tuple[str, ...]


def classify_concentration_risk(
    contributions: Sequence[float],
    *,
    event_months: Sequence[str] | None = None,
    event_timestamps: Sequence[int] | None = None,
    min_events: int = DEFAULT_MIN_EVENTS,
    top_n: int = TOP_N_DEFAULT,
) -> ConcentrationRiskClassification:
    """Classify concentration risk using canonical policy thresholds.

    Verdicts
    --------
    ``insufficient_evidence``
        ``len(contributions) < min_events``.
    ``high_concentration_risk``
        At least one of: single event > 20 %, top 3 > 50 %, one month > 40 %.
    ``acceptable``
        Sufficient events and no concentration breach.
    """
    vals = _validate_contributions(contributions)
    count = event_count_sufficiency(len(vals), min_events=min_events)

    if not count.sufficient:
        empty_single = MaxSingleEventContribution(
            max_share=0.0,
            event_index=-1,
            contribution=0.0,
            total_abs=0.0,
            high_risk=False,
        )
        empty_top = TopNEventsContribution(
            top_n=top_n,
            combined_share=0.0,
            event_indices=(),
            total_abs=0.0,
            high_risk=False,
        )
        empty_month = MaxMonthContribution(
            max_share=0.0,
            month="",
            total_abs=0.0,
            high_risk=False,
            month_shares=(),
        )
        return ConcentrationRiskClassification(
            verdict="insufficient_evidence",
            insufficient_evidence=True,
            single_event_high_risk=False,
            top_n_high_risk=False,
            month_high_risk=False,
            max_single=empty_single,
            top_n=empty_top,
            max_month=empty_month,
            event_count=count,
            reasons=(
                f"event count {count.n_events} < min_events {count.min_events}",
            ),
        )

    single = max_single_event_contribution(vals)
    top = top_n_events_contribution(vals, n=top_n)
    month = max_month_contribution(
        vals,
        event_months=event_months,
        event_timestamps=event_timestamps,
    )

    reasons: list[str] = []
    if single.high_risk:
        reasons.append(
            f"single event share {single.max_share:.1%} > "
            f"{SINGLE_EVENT_HIGH_RISK_SHARE:.0%}"
        )
    if top.high_risk:
        reasons.append(
            f"top {top_n} share {top.combined_share:.1%} > "
            f"{TOP_N_HIGH_RISK_SHARE:.0%}"
        )
    if month.high_risk:
        reasons.append(
            f"month {month.month!r} share {month.max_share:.1%} > "
            f"{MONTH_HIGH_RISK_SHARE:.0%}"
        )

    if reasons:
        verdict = "high_concentration_risk"
    else:
        verdict = "acceptable"

    return ConcentrationRiskClassification(
        verdict=verdict,
        insufficient_evidence=False,
        single_event_high_risk=single.high_risk,
        top_n_high_risk=top.high_risk,
        month_high_risk=month.high_risk,
        max_single=single,
        top_n=top,
        max_month=month,
        event_count=count,
        reasons=tuple(reasons),
    )


def contributions_from_mapping(mapping: Mapping[str, float]) -> tuple[float, ...]:
    """Stable ordering helper for tests and scripts (sorted by key)."""
    return tuple(float(mapping[k]) for k in sorted(mapping))


__all__ = [
    "SINGLE_EVENT_HIGH_RISK_SHARE",
    "TOP_N_HIGH_RISK_SHARE",
    "TOP_N_DEFAULT",
    "MONTH_HIGH_RISK_SHARE",
    "DEFAULT_MIN_EVENTS",
    "MaxSingleEventContribution",
    "max_single_event_contribution",
    "TopNEventsContribution",
    "top_n_events_contribution",
    "MaxMonthContribution",
    "max_month_contribution",
    "EventCountSufficiency",
    "event_count_sufficiency",
    "ConcentrationRiskClassification",
    "classify_concentration_risk",
    "contributions_from_mapping",
]
