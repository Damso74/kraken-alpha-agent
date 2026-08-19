"""Safe scheduler loop for paper daemon (Phase 19)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LoopConfig:
    interval_seconds: float = 60.0
    max_iterations: int = 1
    allow_infinite: bool = False
    lock_file_name: str = ".daemon.lock"


class DaemonLockError(Exception):
    pass


class StaleDataError(Exception):
    pass


def acquire_lock(state_dir: Path, name: str = ".daemon.lock") -> Path:
    lock = state_dir / name
    state_dir.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        raise DaemonLockError(f"lock exists: {lock}")
    lock.write_text(str(time.time()), encoding="utf-8")
    return lock


def release_lock(lock: Path) -> None:
    if lock.is_file():
        lock.unlink(missing_ok=True)


def run_daemon_loop(
    tick: Callable[[], bool],
    *,
    interval_seconds: float = 60.0,
    max_iterations: int = 1,
    allow_infinite: bool = False,
) -> int:
    """Run tick() repeatedly. tick returns False to stop early."""
    if max_iterations <= 0 and not allow_infinite:
        max_iterations = 1
    iterations = 0
    while True:
        keep_going = tick()
        iterations += 1
        if not keep_going:
            break
        if max_iterations > 0 and iterations >= max_iterations:
            break
        if max_iterations <= 0 and not allow_infinite:
            break
        time.sleep(interval_seconds)
    return iterations


def is_stale_data(
    last_ts: int | None,
    latest_ts: int,
    *,
    max_age_seconds: int = 86400 * 3,
) -> bool:
    if last_ts is None:
        return False
    if latest_ts <= last_ts:
        return True
    return (latest_ts - last_ts) > max_age_seconds


def is_duplicate_candle(last_ts: int | None, candle_ts: int) -> bool:
    return last_ts is not None and candle_ts <= last_ts
