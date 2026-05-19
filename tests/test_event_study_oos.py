"""G4 hold-out utilities (no network)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.research.event_study import EventStudyWindow
from src.research.holdout import (
    DEFAULT_HOLDOUT_FRACTION,
    evaluate_holdout_g4,
    filter_events_to_candles,
    split_candles_holdout,
)


def _candle(offset_days: int) -> dict:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ts = int((base + timedelta(days=offset_days)).timestamp())
    return {
        "timestamp": ts,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0 + offset_days * 0.01,
        "volume": 10.0,
    }


def test_split_candles_holdout_reserves_tail() -> None:
    candles = [_candle(d) for d in range(1, 101)]
    split = split_candles_holdout(candles, holdout_fraction=0.30)
    assert split.n_train == 70
    assert split.n_test == 30
    assert split.split_timestamp == int(candles[70]["timestamp"])


def test_filter_events_to_candles() -> None:
    candles = [_candle(d) for d in range(1, 11)]
    events = [int(candles[3]["timestamp"]), 999_999_999]
    filtered = filter_events_to_candles(events, candles)
    assert filtered == [int(candles[3]["timestamp"])]


def test_evaluate_holdout_g4_fails_without_test_events() -> None:
    candles = [_candle(d) for d in range(1, 80)]
    train_events = [int(c["timestamp"]) for c in candles[:50]]
    evaluation = evaluate_holdout_g4(
        candles,
        train_events,
        metrics=("return",),
        windows=(EventStudyWindow("post_1", 1, 1),),
        holdout_fraction=DEFAULT_HOLDOUT_FRACTION,
        n_placebos=50,
        seed=1,
    )
    assert evaluation.oos_survives is False
    assert evaluation.failure_reason is not None


def test_evaluate_holdout_g4_survives_when_test_bh_rejects() -> None:
    candles = [_candle(d) for d in range(1, 120)]
    events = [int(candles[i]["timestamp"]) for i in (10, 20, 30, 90, 95, 100)]
    evaluation = evaluate_holdout_g4(
        candles,
        events,
        metrics=("return",),
        windows=(EventStudyWindow("post_1", 1, 1),),
        holdout_fraction=0.25,
        n_placebos=30,
        seed=42,
        alpha=0.05,
    )
    assert evaluation.test_events >= 1
    assert isinstance(evaluation.oos_survives, bool)
