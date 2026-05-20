"""Tests for daemon loop (Phase 19)."""

from __future__ import annotations

import pytest

from src.bot.daemon_loop import (
    DaemonLockError,
    acquire_lock,
    is_duplicate_candle,
    is_stale_data,
    release_lock,
    run_daemon_loop,
)


def test_run_daemon_loop_finite(tmp_path) -> None:
    count = {"n": 0}

    def tick() -> bool:
        count["n"] += 1
        return count["n"] < 3

    iters = run_daemon_loop(tick, interval_seconds=0.001, max_iterations=10)
    assert iters == 3


def test_lock_prevents_double_daemon(tmp_path) -> None:
    lock = acquire_lock(tmp_path)
    with pytest.raises(DaemonLockError):
        acquire_lock(tmp_path)
    release_lock(lock)


def test_duplicate_and_stale_detection() -> None:
    assert is_duplicate_candle(100, 100)
    assert is_stale_data(100, 200, max_age_seconds=50)
