"""US-equity session classification — shared helpers.

This module is the single source of truth for "what trading session is it
right now?" so the agent loop, the backtester, and the validation scripts
all agree on US_CORE / US_PREMARKET / US_AFTERHOURS / OVERNIGHT / WEEKEND.

The original implementation lived in :mod:`src.backtest` (and still does,
for backwards compatibility with the existing market-hours tests). The
backtest module now re-exports the classifier from here so there is one
real definition.

Timezone is ``America/New_York`` via :mod:`zoneinfo` (``tzdata`` is a
hard dependency, see :file:`requirements.txt`). Boundaries are
inclusive-left and exclusive-right, matching the
:func:`tests.test_market_hours` expectations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — Python <3.9
    ZoneInfo = None  # type: ignore[assignment]


NY_TZ = ZoneInfo("America/New_York") if ZoneInfo is not None else None


class MarketSession(str, Enum):
    """Coarse US-equity session bucket for a UTC timestamp."""

    US_CORE = "US_CORE"
    US_PREMARKET = "US_PREMARKET"
    US_AFTERHOURS = "US_AFTERHOURS"
    OVERNIGHT = "OVERNIGHT"
    WEEKEND = "WEEKEND"


def _parse_iso_to_utc(ts: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if not ts:
        raise ValueError("empty timestamp")
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    parsed = datetime.fromisoformat(s)
    if parsed.tzinfo is None:
        raise ValueError("ISO timestamp without timezone is rejected")
    return parsed.astimezone(UTC)


def classify_market_session(ts_utc: datetime) -> MarketSession:
    """Return the :class:`MarketSession` for a UTC-aware datetime.

    Boundaries (America/New_York):
    - WEEKEND: Saturday and Sunday (any time of day)
    - US_PREMARKET: weekday 04:00:00–09:30:00
    - US_CORE: weekday 09:30:00–16:00:00
    - US_AFTERHOURS: weekday 16:00:00–20:00:00
    - OVERNIGHT: weekday 00:00:00–04:00:00 and 20:00:00–24:00:00
    """
    if not isinstance(ts_utc, datetime):
        raise ValueError("classify_market_session expects a datetime")
    if ts_utc.tzinfo is None:
        raise ValueError("naive datetime rejected; supply an aware UTC datetime")
    if NY_TZ is None:  # pragma: no cover
        raise RuntimeError("zoneinfo unavailable; install tzdata")
    local = ts_utc.astimezone(NY_TZ)
    weekday = local.weekday()
    if weekday >= 5:
        return MarketSession.WEEKEND
    minutes = local.hour * 60 + local.minute + local.second / 60.0
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return MarketSession.US_PREMARKET
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return MarketSession.US_CORE
    if 16 * 60 <= minutes < 20 * 60:
        return MarketSession.US_AFTERHOURS
    return MarketSession.OVERNIGHT


def current_session(now: datetime | None = None) -> MarketSession:
    """Convenience helper returning the session for ``now`` (UTC)."""
    if now is None:
        now = datetime.now(UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return classify_market_session(now)


def is_entry_allowed(
    allowed: list[str] | tuple[str, ...] | None,
    now: datetime | None = None,
) -> tuple[bool, MarketSession]:
    """Return ``(allowed?, current_session)`` for the entry-session guard.

    An empty / falsy ``allowed`` list means "no guard" (any session is OK).
    Unknown labels in ``allowed`` are ignored silently so an out-of-date
    config can never accidentally disable the guard.
    """
    session = current_session(now)
    if not allowed:
        return True, session
    allowed_norm = {a.strip().upper() for a in allowed if a}
    return session.value in allowed_norm, session


def minutes_until_us_core_close(now: datetime | None = None) -> float | None:
    """Return the minutes remaining before 16:00 ET *today*.

    ``None`` when ``now`` is outside the regular weekday window (so the
    flatten-before-close rule should not fire) or when ``zoneinfo`` is
    unavailable. The result is non-negative.
    """
    if now is None:
        now = datetime.now(UTC)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if NY_TZ is None:  # pragma: no cover
        return None
    local = now.astimezone(NY_TZ)
    if local.weekday() >= 5:
        return None
    close = local.replace(hour=16, minute=0, second=0, microsecond=0)
    if local >= close:
        return None
    return max(0.0, (close - local).total_seconds() / 60.0)


__all__ = [
    "MarketSession",
    "NY_TZ",
    "classify_market_session",
    "current_session",
    "is_entry_allowed",
    "minutes_until_us_core_close",
    "_parse_iso_to_utc",
]
