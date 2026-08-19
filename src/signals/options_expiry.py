"""Monthly options expiry boundary events (third Friday, no network).

Row shape
---------
Standard OHLC rows with ``timestamp`` (int, unix UTC). Only timestamps
are read; prices are ignored.

Hypothesis
----------
Dealer gamma hedging around listed expiry can pin or accelerate moves
in BTC/ETH; crypto perps may show elevated volatility into the close.

Overfit risk
------------
Expiry effects weakened as crypto options depth grew; easy to cherry-pick
one asset or one year.

Rejection condition
-------------------
Reject when the effect is not significant vs placebo Fridays or when
only a single expiry month drives results.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

from ._stats import extract_timestamp, sort_rows_by_timestamp


def _third_friday(year: int, month: int) -> date:
    """Return the calendar date of the third Friday in ``month``/``year``."""
    first_weekday, days_in_month = monthrange(year, month)
    # weekday(): Monday=0 … Sunday=6; Friday=4
    first_day = date(year, month, 1)
    days_until_friday = (4 - first_day.weekday()) % 7
    first_friday = 1 + days_until_friday
    third_friday_day = first_friday + 14
    if third_friday_day > days_in_month:
        raise ValueError(f"invalid third Friday for {year}-{month}")
    return date(year, month, third_friday_day)


def _is_third_friday_utc(ts: int) -> bool:
    dt = datetime.fromtimestamp(ts, tz=UTC)
    d = dt.date()
    if d.weekday() != 4:
        return False
    return d == _third_friday(d.year, d.month)


def build_monthly_options_expiry_events(
    rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    """First OHLC candle on each third-Friday UTC expiry day in the sample."""
    sorted_rows = sort_rows_by_timestamp(rows)
    events: list[int] = []
    seen_days: set[str] = set()

    for row in sorted_rows:
        ts = extract_timestamp(row)
        if ts is None or not _is_third_friday_utc(ts):
            continue
        day_key = datetime.fromtimestamp(ts, tz=UTC).date().isoformat()
        if day_key in seen_days:
            continue
        seen_days.add(day_key)
        events.append(ts)

    return events


__all__ = ["build_monthly_options_expiry_events"]
