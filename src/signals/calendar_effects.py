"""Calendar / session boundary events from OHLC timestamps (no network).

Row shape
---------
Uses standard OHLC rows:

- ``timestamp`` (int): unix seconds UTC
- ``open``, ``high``, ``low``, ``close``, ``volume`` (floats)

Hypothesis
----------
Weekend liquidity drops and session opens (US cash, Asia) inject
predictable microstructure patterns in 24/7 crypto markets.

Phase 11 micro-baselines (pre-registered, daily OHLC only)
----------------------------------------------------------
Five fixed calendar effects — **no hourly grid search**:

1. ``us_market_open_window`` — US equity weekday (Mon–Fri ET)
2. ``sunday_us_evening`` — Sunday calendar day (America/New_York)
3. ``monday_asia_open`` — Monday calendar day (Asia/Tokyo)
4. ``third_friday`` — third Friday UTC (options expiry proxy)
5. ``month_end`` — last UTC calendar day with a candle each month

Overfit risk
------------
Extremely easy to data-mine — many timezone/session definitions fit
in-sample. Prefer pre-registered session definitions.

Rejection condition
-------------------
Reject when effects disappear on a hold-out year or when only one
pair drives the aggregate event-study result.
"""

from __future__ import annotations

import random
from calendar import monthrange
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from ._stats import extract_timestamp, sort_rows_by_timestamp

_ET = ZoneInfo("America/New_York")
_TOKYO = ZoneInfo("Asia/Tokyo")

# Canonical Phase 11 sprint IDs (fixed; no post-hoc hour tuning).
PRE_REGISTERED_CALENDAR_EFFECTS: tuple[str, ...] = (
    "us_market_open_window",
    "sunday_us_evening",
    "monday_asia_open",
    "third_friday",
    "month_end",
)

# On daily UTC OHLC, Sunday ET and Monday Tokyo pick the same candle timestamps
# (red team Phase 11). Phase 12 runs the canonical effect only.
CALENDAR_EFFECT_DAILY_ALIASES: dict[str, str] = {
    "monday_asia_open": "sunday_us_evening",
}


def resolve_calendar_effect_id(effect_id: str) -> str:
    """Map alias effect ids to their canonical pre-registered id."""
    return CALENDAR_EFFECT_DAILY_ALIASES.get(effect_id, effect_id)


def is_calendar_effect_alias(effect_id: str) -> bool:
    return effect_id in CALENDAR_EFFECT_DAILY_ALIASES


def calendar_effects_for_event_study() -> tuple[str, ...]:
    """Distinct effects to execute (aliases excluded from runs)."""
    return tuple(e for e in PRE_REGISTERED_CALENDAR_EFFECTS if not is_calendar_effect_alias(e))


def _dedupe_timestamps(timestamps: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for ts in sorted(timestamps):
        if ts not in seen:
            seen.add(ts)
            out.append(ts)
    return out


def _one_event_per_local_day(
    rows: Sequence[Mapping[str, Any]],
    *,
    tz: ZoneInfo,
    day_predicate: Callable[[date], bool],
) -> list[int]:
    """First candle per local calendar day matching ``day_predicate``."""
    sorted_rows = sort_rows_by_timestamp(rows)
    events: list[int] = []
    seen_days: set[str] = set()

    for row in sorted_rows:
        ts = extract_timestamp(row)
        if ts is None:
            continue
        local_date = datetime.fromtimestamp(ts, tz=tz).date()
        if not day_predicate(local_date):
            continue
        day_key = local_date.isoformat()
        if day_key in seen_days:
            continue
        seen_days.add(day_key)
        events.append(ts)

    return events


def _third_friday_date(year: int, month: int) -> date:
    first_day = date(year, month, 1)
    days_until_friday = (4 - first_day.weekday()) % 7
    third_friday_day = 1 + days_until_friday + 14
    _, days_in_month = monthrange(year, month)
    if third_friday_day > days_in_month:
        raise ValueError(f"invalid third Friday for {year}-{month}")
    return date(year, month, third_friday_day)


def build_us_market_open_window_events(
    rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    """US equity weekday proxy: Mon–Fri in ``America/New_York`` (daily OHLC)."""
    return _one_event_per_local_day(
        rows,
        tz=_ET,
        day_predicate=lambda d: d.weekday() < 5,
    )


def build_sunday_us_evening_events(
    rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    """Sunday US evening proxy: Sunday calendar day in ``America/New_York``."""
    return _one_event_per_local_day(
        rows,
        tz=_ET,
        day_predicate=lambda d: d.weekday() == 6,
    )


def build_monday_asia_open_events(
    rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    """Monday Asia open proxy: Monday calendar day in ``Asia/Tokyo``."""
    return _one_event_per_local_day(
        rows,
        tz=_TOKYO,
        day_predicate=lambda d: d.weekday() == 0,
    )


def build_third_friday_events(
    rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    """First daily candle on each third-Friday UTC expiry day."""
    sorted_rows = sort_rows_by_timestamp(rows)
    events: list[int] = []
    seen_days: set[str] = set()

    for row in sorted_rows:
        ts = extract_timestamp(row)
        if ts is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        d = dt.date()
        if d.weekday() != 4 or d != _third_friday_date(d.year, d.month):
            continue
        day_key = d.isoformat()
        if day_key in seen_days:
            continue
        seen_days.add(day_key)
        events.append(ts)

    return events


def build_month_end_events(
    rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    """Last UTC calendar day with a candle in each month."""
    sorted_rows = sort_rows_by_timestamp(rows)
    last_by_month: dict[tuple[int, int], int] = {}

    for row in sorted_rows:
        ts = extract_timestamp(row)
        if ts is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        last_by_month[(dt.year, dt.month)] = ts

    return sorted(last_by_month.values())


_CALENDAR_EFFECT_BUILDERS: dict[str, Callable[[Sequence[Mapping[str, Any]]], list[int]]] = {
    "us_market_open_window": build_us_market_open_window_events,
    "sunday_us_evening": build_sunday_us_evening_events,
    "monday_asia_open": build_monday_asia_open_events,
    "third_friday": build_third_friday_events,
    "month_end": build_month_end_events,
}


def build_pre_registered_calendar_events(
    rows: Sequence[Mapping[str, Any]],
    effect_id: str,
) -> list[int]:
    """Build events for one Phase 11 pre-registered calendar effect."""
    builder = _CALENDAR_EFFECT_BUILDERS.get(effect_id)
    if builder is None:
        known = ", ".join(PRE_REGISTERED_CALENDAR_EFFECTS)
        raise ValueError(f"unknown calendar effect {effect_id!r}; expected one of {known}")
    return builder(rows)


def placebo_timezone_for_effect(effect_id: str) -> ZoneInfo:
    """Timezone used for same-weekday placebo matching."""
    if effect_id in ("us_market_open_window", "sunday_us_evening"):
        return _ET
    if effect_id == "monday_asia_open":
        return _TOKYO
    return timezone.utc


def random_same_weekday_placebo_events(
    candle_timestamps: Sequence[int],
    template_events: Sequence[int],
    *,
    tz: ZoneInfo,
    seed: int,
) -> list[int]:
    """Draw placebo events on random days sharing the template weekday."""
    pool = [int(t) for t in candle_timestamps]
    if not pool or not template_events:
        return []

    pool_by_weekday: dict[int, list[int]] = {}
    for ts in pool:
        wd = datetime.fromtimestamp(ts, tz=tz).weekday()
        pool_by_weekday.setdefault(wd, []).append(ts)

    rng = random.Random(int(seed))
    out: list[int] = []
    for ev in template_events:
        wd = datetime.fromtimestamp(int(ev), tz=tz).weekday()
        candidates = pool_by_weekday.get(wd, [])
        if not candidates:
            continue
        alt = [t for t in candidates if t != ev] or candidates
        out.append(rng.choice(alt))
    out.sort()
    return out


def build_weekend_start_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    use_utc: bool = True,
) -> list[int]:
    """First candle whose local calendar day is Saturday (weekend boundary).

    Parameters
    ----------
    use_utc:
        When True (default), Saturday is evaluated in UTC; when False,
        uses ``America/New_York`` (US equity weekend proxy for xStocks).
    """
    tz = timezone.utc if use_utc else _ET
    sorted_rows = sort_rows_by_timestamp(rows)
    events: list[int] = []
    last_saturday: str | None = None

    for row in sorted_rows:
        ts = extract_timestamp(row)
        if ts is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=tz)
        if dt.weekday() != 5:  # Saturday
            continue
        key = dt.date().isoformat()
        if key == last_saturday:
            continue
        last_saturday = key
        events.append(ts)

    return events


def build_weekend_end_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    use_utc: bool = True,
) -> list[int]:
    """First candle whose local calendar day is Monday (weekend exit)."""
    tz = timezone.utc if use_utc else _ET
    sorted_rows = sort_rows_by_timestamp(rows)
    events: list[int] = []
    last_monday: str | None = None

    for row in sorted_rows:
        ts = extract_timestamp(row)
        if ts is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=tz)
        if dt.weekday() != 0:  # Monday
            continue
        key = dt.date().isoformat()
        if key == last_monday:
            continue
        last_monday = key
        events.append(ts)

    return events


def _session_open_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    tz: ZoneInfo,
    open_hour: int,
    open_minute: int,
) -> list[int]:
    """First candle at or after ``open_hour:open_minute`` on each local day."""
    sorted_rows = sort_rows_by_timestamp(rows)
    events: list[int] = []
    seen_days: set[str] = set()

    for row in sorted_rows:
        ts = extract_timestamp(row)
        if ts is None:
            continue
        dt = datetime.fromtimestamp(ts, tz=tz)
        day_key = dt.date().isoformat()
        if day_key in seen_days:
            continue
        open_dt = dt.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0)
        if dt < open_dt:
            continue
        seen_days.add(day_key)
        events.append(ts)

    return events


def build_us_core_session_open_events(
    rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    """US cash equity open proxy: first candle at/after 09:30 America/New_York."""
    return _session_open_events(rows, tz=_ET, open_hour=9, open_minute=30)


def build_asia_session_open_events(
    rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    """Tokyo cash session open proxy: first candle at/after 09:00 Asia/Tokyo."""
    return _session_open_events(rows, tz=_TOKYO, open_hour=9, open_minute=0)


def build_calendar_boundary_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    flags: Sequence[str] = ("weekend_start", "us_open"),
) -> list[int]:
    """Combine multiple calendar flags into one deduplicated event list.

    Supported ``flags``:

    - ``weekend_start``, ``weekend_end``
    - ``us_open``, ``asia_open``
    """
    builders: dict[str, Any] = {
        "weekend_start": lambda r: build_weekend_start_events(r),
        "weekend_end": lambda r: build_weekend_end_events(r),
        "us_open": lambda r: build_us_core_session_open_events(r),
        "asia_open": lambda r: build_asia_session_open_events(r),
    }
    all_ts: list[int] = []
    for flag in flags:
        fn = builders.get(flag)
        if fn is None:
            raise ValueError(f"unknown calendar flag {flag!r}")
        all_ts.extend(fn(rows))
    return _dedupe_timestamps(all_ts)


__all__ = [
    "PRE_REGISTERED_CALENDAR_EFFECTS",
    "build_pre_registered_calendar_events",
    "build_us_market_open_window_events",
    "build_sunday_us_evening_events",
    "build_monday_asia_open_events",
    "build_third_friday_events",
    "build_month_end_events",
    "placebo_timezone_for_effect",
    "random_same_weekday_placebo_events",
    "build_weekend_start_events",
    "build_weekend_end_events",
    "build_us_core_session_open_events",
    "build_asia_session_open_events",
    "build_calendar_boundary_events",
]
