"""Tests for :mod:`src.signals.calendar_effects`."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.signals.calendar_effects import (
    PRE_REGISTERED_CALENDAR_EFFECTS,
    build_calendar_boundary_events,
    build_monday_asia_open_events,
    build_month_end_events,
    build_pre_registered_calendar_events,
    build_sunday_us_evening_events,
    build_third_friday_events,
    build_us_core_session_open_events,
    build_us_market_open_window_events,
    build_weekend_start_events,
    placebo_timezone_for_effect,
    random_same_weekday_placebo_events,
)

_ET = ZoneInfo("America/New_York")
_TOKYO = ZoneInfo("Asia/Tokyo")


def _ohlc(ts: int) -> dict:
    return {
        "timestamp": ts,
        "open": 100.0,
        "high": 100.0,
        "low": 100.0,
        "close": 100.0,
        "volume": 1.0,
    }


def test_pre_registered_registry_has_five_effects() -> None:
    assert len(PRE_REGISTERED_CALENDAR_EFFECTS) == 5
    assert "us_market_open_window" in PRE_REGISTERED_CALENDAR_EFFECTS
    assert "third_friday" in PRE_REGISTERED_CALENDAR_EFFECTS


def test_weekend_start_first_saturday_candle() -> None:
    # 2024-01-06 is Saturday UTC
    sat = int(datetime(2024, 1, 6, 1, 0, tzinfo=timezone.utc).timestamp())
    fri = int(datetime(2024, 1, 5, 23, 0, tzinfo=timezone.utc).timestamp())
    events = build_weekend_start_events([_ohlc(fri), _ohlc(sat)])
    assert events == [sat]


def test_us_core_session_open_first_candle_after_0930_et() -> None:
    # Monday 2024-01-08 09:00 ET (before open) and 10:00 ET (after open)
    pre = datetime(2024, 1, 8, 9, 0, tzinfo=_ET)
    post = datetime(2024, 1, 8, 10, 0, tzinfo=_ET)
    events = build_us_core_session_open_events(
        [_ohlc(int(pre.timestamp())), _ohlc(int(post.timestamp()))]
    )
    assert len(events) == 1
    assert events[0] == int(post.timestamp())


def test_us_market_open_window_weekdays_only_et() -> None:
    mon = int(datetime(2024, 1, 8, 12, 0, tzinfo=_ET).timestamp())
    sat = int(datetime(2024, 1, 6, 12, 0, tzinfo=_ET).timestamp())
    events = build_us_market_open_window_events([_ohlc(sat), _ohlc(mon)])
    assert events == [mon]


def test_sunday_us_evening_picks_sunday_et() -> None:
    sun = int(datetime(2024, 1, 7, 20, 0, tzinfo=_ET).timestamp())
    mon = int(datetime(2024, 1, 8, 20, 0, tzinfo=_ET).timestamp())
    events = build_sunday_us_evening_events([_ohlc(mon), _ohlc(sun)])
    assert events == [sun]


def test_monday_asia_open_picks_monday_tokyo() -> None:
    mon = int(datetime(2024, 1, 8, 10, 0, tzinfo=_TOKYO).timestamp())
    tue = int(datetime(2024, 1, 9, 10, 0, tzinfo=_TOKYO).timestamp())
    events = build_monday_asia_open_events([_ohlc(tue), _ohlc(mon)])
    assert events == [mon]


def test_third_friday_january_2024() -> None:
    # Third Friday Jan 2024 = 2024-01-19 (UTC daily candle)
    third = int(datetime(2024, 1, 19, 0, 0, tzinfo=timezone.utc).timestamp())
    second = int(datetime(2024, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp())
    events = build_third_friday_events([_ohlc(second), _ohlc(third)])
    assert events == [third]


def test_month_end_last_candle_per_month() -> None:
    jan_mid = int(datetime(2024, 1, 15, 0, 0, tzinfo=timezone.utc).timestamp())
    jan_end = int(datetime(2024, 1, 31, 0, 0, tzinfo=timezone.utc).timestamp())
    feb_end = int(datetime(2024, 2, 29, 0, 0, tzinfo=timezone.utc).timestamp())
    events = build_month_end_events(
        [_ohlc(jan_mid), _ohlc(jan_end), _ohlc(feb_end)]
    )
    assert events == [jan_end, feb_end]


def test_build_pre_registered_calendar_events_dispatcher() -> None:
    sun = int(datetime(2024, 1, 7, 20, 0, tzinfo=_ET).timestamp())
    events = build_pre_registered_calendar_events([_ohlc(sun)], "sunday_us_evening")
    assert events == [sun]


def test_random_same_weekday_preserves_weekday() -> None:
    mon = int(datetime(2024, 1, 8, 0, 0, tzinfo=_ET).timestamp())
    tue = int(datetime(2024, 1, 9, 0, 0, tzinfo=_ET).timestamp())
    wed = int(datetime(2024, 1, 10, 0, 0, tzinfo=_ET).timestamp())
    next_mon = int(datetime(2024, 1, 15, 0, 0, tzinfo=_ET).timestamp())
    template = [mon]
    pool = [mon, tue, wed, next_mon]
    placebo = random_same_weekday_placebo_events(
        pool,
        template,
        tz=_ET,
        seed=42,
    )
    assert len(placebo) == 1
    assert datetime.fromtimestamp(placebo[0], tz=_ET).weekday() == 0


def test_placebo_timezone_for_effect() -> None:
    assert placebo_timezone_for_effect("us_market_open_window") == _ET
    assert placebo_timezone_for_effect("monday_asia_open") == _TOKYO
    assert placebo_timezone_for_effect("third_friday") == timezone.utc


def test_calendar_boundary_combines_flags() -> None:
    sat = int(datetime(2024, 1, 6, 12, 0, tzinfo=timezone.utc).timestamp())
    mon_post = datetime(2024, 1, 8, 10, 0, tzinfo=_ET)
    rows = [_ohlc(sat), _ohlc(int(mon_post.timestamp()))]
    events = build_calendar_boundary_events(
        rows, flags=("weekend_start", "us_open")
    )
    assert sat in events
    assert int(mon_post.timestamp()) in events


def test_empty_ohlc_returns_empty() -> None:
    assert build_weekend_start_events([]) == []
    assert build_pre_registered_calendar_events([], "month_end") == []
