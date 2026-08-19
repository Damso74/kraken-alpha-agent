"""Exchange status / incident events from provider status pages.

Row shape
---------
Each row is a mapping with:

- ``timestamp`` (int): unix seconds UTC (incident start or update time)
- ``impact`` (str): ``"none"`` | ``"minor"`` | ``"major"`` | ``"critical"``
  (case-insensitive; unknown values are ignored)
- ``component`` (str): affected subsystem label
- ``provider`` (str): exchange identifier (e.g. ``"kraken"``, ``"coinbase"``)
- ``name`` (str, optional): incident title — used for scheduled/unscheduled split
- ``started_at`` / ``updated_at`` (str, optional): ISO-8601 Z for duration filters

Hypothesis
----------
Operational incidents impair liquidity and widen spreads; major outages
may cause short-term volatility or delayed reactions when service resumes.

Overfit risk
------------
Sparse events — easy to overfit a handful of memorable incidents.

Rejection condition
-------------------
Reject when sample size < 10 incidents at the chosen impact tier or when
post-event moves are explained by concurrent macro events alone.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from ._stats import extract_timestamp, sort_rows_by_timestamp

_IMPACT_RANK: dict[str, int] = {
    "none": 0,
    "minor": 1,
    "major": 2,
    "critical": 3,
}

IncidentKind = Literal["scheduled", "unscheduled"]
IncidentKindFilter = Literal["all", "scheduled", "unscheduled"]

_MAINTENANCE_KEYWORDS: tuple[str, ...] = (
    "maintenance",
    "scheduled",
    "planned",
)

_SCHEDULED_NAME_RE = re.compile(
    r"\b(maintenance|scheduled|planned)\b",
    re.IGNORECASE,
)


def _normalize_impact(raw: Any) -> str | None:
    if raw is None:
        return None
    key = str(raw).strip().lower()
    if key not in _IMPACT_RANK:
        return None
    return key


def classify_incident_kind(row: Mapping[str, Any]) -> IncidentKind:
    """Classify a status-page row as scheduled maintenance vs unscheduled."""
    name = str(row.get("name") or "")
    if _SCHEDULED_NAME_RE.search(name):
        return "scheduled"
    for kw in _MAINTENANCE_KEYWORDS:
        if kw in name.lower():
            return "scheduled"
    return "unscheduled"


def incident_duration_minutes(row: Mapping[str, Any]) -> float | None:
    """Return incident duration in minutes from ``started_at`` → ``updated_at``."""
    started = str(row.get("started_at") or "").strip()
    updated = str(row.get("updated_at") or "").strip()
    if not started or not updated:
        return None

    def _parse_iso(s: str) -> datetime | None:
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            return None

    t0 = _parse_iso(started)
    t1 = _parse_iso(updated)
    if t0 is None or t1 is None:
        return None
    delta = (t1 - t0).total_seconds() / 60.0
    if delta < 0:
        return None
    return float(delta)


def build_exchange_status_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_impact: str = "minor",
    impact_exact: str | None = None,
    providers: Sequence[str] | None = None,
    components: Sequence[str] | None = None,
    incident_kind: IncidentKindFilter = "all",
    min_duration_minutes: float | None = None,
) -> list[int]:
    """Emit incident timestamps matching the configured filters.

    Parameters
    ----------
    rows:
        Status-page incident rows (see module docstring).
    min_impact:
        Minimum severity to include (``"minor"``, ``"major"``,
        ``"critical"``). Ignored when ``impact_exact`` is set.
    impact_exact:
        When set, only rows whose normalized impact equals this tier
        qualify (e.g. ``"major"`` only — not major+critical).
    providers:
        When set, only rows whose ``provider`` is in this set qualify.
    components:
        When set, only rows whose ``component`` is in this set qualify.
    incident_kind:
        ``"scheduled"`` | ``"unscheduled"`` | ``"all"`` (default all).
    min_duration_minutes:
        When set, require ``started_at``/``updated_at`` span ≥ this many
        minutes. Rows without parseable duration are excluded.

    Returns
    -------
    list[int]
        Unix UTC timestamps, ascending, deduplicated.
    """
    if impact_exact is not None:
        exact_key = _normalize_impact(impact_exact)
        if exact_key is None or exact_key not in _IMPACT_RANK:
            raise ValueError(
                f"impact_exact must be one of minor/major/critical/none, "
                f"got {impact_exact!r}"
            )
        min_rank = None
    else:
        min_key = _normalize_impact(min_impact)
        if min_key is None or min_key not in _IMPACT_RANK:
            raise ValueError(
                f"min_impact must be one of minor/major/critical, got {min_impact!r}"
            )
        min_rank = _IMPACT_RANK[min_key]
        exact_key = None

    if incident_kind not in ("all", "scheduled", "unscheduled"):
        raise ValueError(
            f"incident_kind must be all/scheduled/unscheduled, got {incident_kind!r}"
        )

    provider_set = {p.lower() for p in providers} if providers else None
    component_set = {c.lower() for c in components} if components else None

    sorted_rows = sort_rows_by_timestamp(rows)
    events: list[int] = []
    seen: set[int] = set()

    for row in sorted_rows:
        impact = _normalize_impact(row.get("impact"))
        if impact is None:
            continue
        if exact_key is not None:
            if impact != exact_key:
                continue
        elif min_rank is not None and _IMPACT_RANK[impact] < min_rank:
            continue

        kind = classify_incident_kind(row)
        if incident_kind == "scheduled" and kind != "scheduled":
            continue
        if incident_kind == "unscheduled" and kind != "unscheduled":
            continue

        if min_duration_minutes is not None:
            dur = incident_duration_minutes(row)
            if dur is None or dur < float(min_duration_minutes):
                continue

        if provider_set is not None:
            prov = str(row.get("provider", "")).strip().lower()
            if prov not in provider_set:
                continue
        if component_set is not None:
            comp = str(row.get("component", "")).strip().lower()
            if comp not in component_set:
                continue
        ts = extract_timestamp(row)
        if ts is None or ts in seen:
            continue
        seen.add(ts)
        events.append(ts)

    return events


def count_rows_by_impact(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Diagnostic histogram of normalized impact tiers."""
    counts: dict[str, int] = {k: 0 for k in _IMPACT_RANK}
    for row in rows:
        impact = _normalize_impact(row.get("impact"))
        if impact is not None:
            counts[impact] += 1
    return counts


def count_rows_by_kind(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Diagnostic counts for scheduled vs unscheduled classification."""
    out = {"scheduled": 0, "unscheduled": 0}
    for row in rows:
        out[classify_incident_kind(row)] += 1
    return out


__all__ = [
    "IncidentKind",
    "IncidentKindFilter",
    "build_exchange_status_events",
    "classify_incident_kind",
    "count_rows_by_impact",
    "count_rows_by_kind",
    "incident_duration_minutes",
]
