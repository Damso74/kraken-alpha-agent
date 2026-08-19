"""Phase 12 exchange status placebo bootstrap (no network)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "event_study_exchange_status",
    _REPO / "scripts" / "event_study_exchange_status.py",
)
_mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_mod)

_random_timestamp_bootstrap_p = _mod._random_timestamp_bootstrap_p
EventStudyWindow = _mod.EventStudyWindow


def _candle(offset_days: int) -> dict:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    ts = int((base + timedelta(days=offset_days)).timestamp())
    return {
        "timestamp": ts,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 1.0,
    }


def test_random_timestamp_bootstrap_returns_p_value() -> None:
    candles = [_candle(d) for d in range(1, 120)]
    events = [
        int(candles[i]["timestamp"]) for i in (10, 20, 30, 40, 50, 60, 70, 80)
    ]
    window = EventStudyWindow("post_3", 1, 3)
    p = _random_timestamp_bootstrap_p(
        candles=candles,
        events=events,
        metric="return",
        window=window,
        n_placebos=40,
        seed=7,
    )
    assert p is not None
    assert 0.0 <= p <= 1.0
