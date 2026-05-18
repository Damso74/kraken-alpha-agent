"""Regression tests for :mod:`src.live_killswitch`.

Invariants under test:

- ``KillSwitchConfig`` clamps positive thresholds and tiny intervals so
  an operator typo cannot silently disable the switch.
- ``KillSwitchOrchestrator.run`` fires on a cumulative PnL drop at or
  below the threshold, calls ``cancel_all`` + ``flatten_positions`` +
  ``terminate_subprocess`` in that order, and returns exit code ``1``.
- The orchestrator never fires when cumulative PnL stays above the
  threshold; ``run`` returns ``0`` after the operator requests stop.
- The CEST cut-off helper maps a UTC clock to CEST = UTC+2 and triggers
  once the wall clock reaches the configured hour/minute.
- The max-duration ceiling triggers a flatten even if PnL never crosses
  the threshold.
- Consecutive snapshot failures past the configured limit promote a
  flatten so a dead PnL source cannot strand open positions.
- ``request_stop`` from a fake SIGINT handler exits the loop cleanly
  and still calls flatten (defence in depth — we never leave positions
  behind at shutdown).
- Events are appended to the JSONL log file as one JSON object per line.

Every test injects a deterministic clock + sleep + PnL source so the
suite stays hermetic. No Kraken CLI calls, no real subprocess.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.live_killswitch import (
    KillSwitchConfig,
    KillSwitchEvent,
    KillSwitchOrchestrator,
    PnLSnapshot,
    cest_cutoff_reached,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ScriptedClock:
    """Wall-clock that returns successive timestamps from a fixed plan."""

    def __init__(self, start: datetime, step: timedelta) -> None:
        self._t = start
        self._step = step
        self._calls = 0

    def __call__(self) -> datetime:
        self._calls += 1
        # Step *after* returning so the very first call reports ``start``.
        cur = self._t
        self._t = self._t + self._step
        return cur


class _SilentSleep:
    """No-op sleep so tests never block on wall-clock time."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(float(seconds))


class _ScriptedPnLSource:
    """Returns successive snapshots from a fixed list. Cycles on overflow."""

    def __init__(self, snapshots: list[PnLSnapshot]) -> None:
        self._snaps = list(snapshots)
        self._idx = 0

    def snapshot(self) -> PnLSnapshot:
        snap = self._snaps[min(self._idx, len(self._snaps) - 1)]
        self._idx += 1
        return snap


class _FailingPnLSource:
    """Raises until ``ok_after`` snapshots, then returns the supplied value."""

    def __init__(self, ok_after: int, ok_snapshot: PnLSnapshot) -> None:
        self._fail_remaining = ok_after
        self._ok = ok_snapshot
        self.calls = 0

    def snapshot(self) -> PnLSnapshot:
        self.calls += 1
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise RuntimeError("simulated kraken futures accounts outage")
        return self._ok


def _snap(pnl: float, *, at: str = "2026-05-18T18:00:00Z") -> PnLSnapshot:
    # Split realized/unrealized arbitrarily; the orchestrator only reads net.
    return PnLSnapshot(
        realized_usd=pnl,
        unrealized_usd=0.0,
        at_iso=at,
        source="scripted",
    )


@pytest.fixture
def tmp_log(tmp_path) -> Path:
    return tmp_path / "killswitch.log"


# ---------------------------------------------------------------------------
# Config clamps
# ---------------------------------------------------------------------------


def test_config_clamps_positive_threshold_to_almost_zero() -> None:
    cfg = KillSwitchConfig(threshold_usd=10.0)
    assert cfg.threshold_usd == pytest.approx(-0.01)


def test_config_clamps_tiny_poll_interval() -> None:
    cfg = KillSwitchConfig(threshold_usd=-5.0, poll_interval_seconds=0.0)
    assert cfg.poll_interval_seconds == pytest.approx(1.0)


def test_config_clamps_tiny_max_duration_and_low_failure_limit() -> None:
    cfg = KillSwitchConfig(
        threshold_usd=-5.0,
        max_duration_seconds=10.0,
        snapshot_failure_limit=0,
    )
    assert cfg.max_duration_seconds == pytest.approx(60.0)
    assert cfg.snapshot_failure_limit == 1


# ---------------------------------------------------------------------------
# CEST cutoff helper
# ---------------------------------------------------------------------------


def test_cest_cutoff_fires_after_2155_local() -> None:
    # 2026-05-18 19:55 UTC = 21:55 CEST → triggers at the boundary.
    boundary = datetime(2026, 5, 18, 19, 55, tzinfo=timezone.utc)
    assert cest_cutoff_reached(boundary, hour=21, minute=55) is True
    before = boundary - timedelta(minutes=1)
    assert cest_cutoff_reached(before, hour=21, minute=55) is False


# ---------------------------------------------------------------------------
# Orchestrator branches
# ---------------------------------------------------------------------------


def test_killswitch_fires_on_pnl_drop_calls_callbacks_in_order(tmp_log: Path) -> None:
    # Baseline at 0, then drops to -5.50 → must trigger on the second snapshot.
    source = _ScriptedPnLSource([
        _snap(0.0),
        _snap(-5.50),
    ])
    call_order: list[str] = []
    cancel_all = lambda: (call_order.append("cancel_all"), {"ok": True})[1]  # noqa: E731
    flatten = lambda: (call_order.append("flatten"), {"ok": True})[1]  # noqa: E731
    terminate = lambda: call_order.append("terminate")  # noqa: E731

    clock = _ScriptedClock(
        start=datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc),
        step=timedelta(seconds=10),
    )
    orch = KillSwitchOrchestrator(
        pnl_source=source,
        config=KillSwitchConfig(threshold_usd=-5.0, poll_interval_seconds=10),
        cancel_all=cancel_all,
        flatten_positions=flatten,
        terminate_subprocess=terminate,
        log_path=tmp_log,
        clock=clock,
        sleep=_SilentSleep(),
    )
    orch.start_session()
    exit_code = orch.run()

    assert exit_code == 1
    assert orch.triggered is True
    assert orch.trigger_reason == "killswitch_pnl"
    assert call_order == ["cancel_all", "flatten", "terminate"]
    lines = [json.loads(line) for line in tmp_log.read_text(encoding="utf-8").splitlines()]
    kinds = [entry["kind"] for entry in lines]
    assert "session_started" in kinds
    assert any(k.startswith("killswitch_triggered:") for k in kinds)
    assert any(k.startswith("flatten_complete:") for k in kinds)


def test_killswitch_does_not_fire_when_pnl_stays_above_threshold(tmp_log: Path) -> None:
    # PnL fluctuates between -2 and +1 — never reaches -5. We let the
    # max-duration ceiling fire as the natural stop so we can compare
    # the *reason*.
    snapshots = [_snap(0.0), _snap(-2.5), _snap(+0.5), _snap(-1.2)]
    source = _ScriptedPnLSource(snapshots)
    call_order: list[str] = []

    clock = _ScriptedClock(
        start=datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc),
        step=timedelta(seconds=10),
    )
    cfg = KillSwitchConfig(
        threshold_usd=-5.0,
        poll_interval_seconds=10,
        max_duration_seconds=60,   # tight ceiling so the test ends fast
    )
    orch = KillSwitchOrchestrator(
        pnl_source=source,
        config=cfg,
        cancel_all=lambda: (call_order.append("cancel_all"), {"ok": True})[1],
        flatten_positions=lambda: (call_order.append("flatten"), {"ok": True})[1],
        terminate_subprocess=lambda: call_order.append("terminate"),
        log_path=tmp_log,
        clock=clock,
        sleep=_SilentSleep(),
    )
    orch.start_session()
    exit_code = orch.run()

    assert orch.trigger_reason == "max_duration_reached"
    assert exit_code == 1  # max_duration is still a trigger → code 1
    # Flatten still ran (defence in depth).
    assert call_order == ["cancel_all", "flatten", "terminate"]


def test_killswitch_fires_on_cest_cutoff(tmp_log: Path) -> None:
    # Start the clock just before 21:55 CEST = 19:55 UTC. With a 5-min step
    # the second `_clock()` call lands in the cut-off window.
    source = _ScriptedPnLSource([_snap(0.0), _snap(0.0)])
    call_order: list[str] = []

    clock = _ScriptedClock(
        start=datetime(2026, 5, 18, 19, 50, tzinfo=timezone.utc),
        step=timedelta(minutes=5),
    )
    cfg = KillSwitchConfig(
        threshold_usd=-5.0,
        poll_interval_seconds=10,
        flatten_cest_hour=21,
        flatten_cest_minute=55,
        max_duration_seconds=24 * 3600,
    )
    orch = KillSwitchOrchestrator(
        pnl_source=source,
        config=cfg,
        cancel_all=lambda: (call_order.append("cancel_all"), {"ok": True})[1],
        flatten_positions=lambda: (call_order.append("flatten"), {"ok": True})[1],
        terminate_subprocess=lambda: call_order.append("terminate"),
        log_path=tmp_log,
        clock=clock,
        sleep=_SilentSleep(),
    )
    orch.start_session()
    exit_code = orch.run()

    assert orch.trigger_reason == "cest_cutoff"
    assert exit_code == 1
    assert call_order == ["cancel_all", "flatten", "terminate"]


def test_killswitch_promotes_repeated_snapshot_failures_to_trigger(tmp_log: Path) -> None:
    # The source fails forever; failure_limit=3 → must fire after 3 fails.
    source = _FailingPnLSource(ok_after=999, ok_snapshot=_snap(0.0))
    # Baseline call always succeeds because we provide an ok_snapshot for
    # the first call by switching the failing source after start_session.
    # Simpler path: provide an ok baseline source, then swap to failing.
    baseline_source = _ScriptedPnLSource([_snap(0.0)])
    cfg = KillSwitchConfig(
        threshold_usd=-5.0,
        poll_interval_seconds=10,
        snapshot_failure_limit=3,
        max_duration_seconds=24 * 3600,
    )
    call_order: list[str] = []
    clock = _ScriptedClock(
        start=datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc),
        step=timedelta(seconds=10),
    )
    orch = KillSwitchOrchestrator(
        pnl_source=baseline_source,
        config=cfg,
        cancel_all=lambda: (call_order.append("cancel_all"), {"ok": True})[1],
        flatten_positions=lambda: (call_order.append("flatten"), {"ok": True})[1],
        terminate_subprocess=lambda: call_order.append("terminate"),
        log_path=tmp_log,
        clock=clock,
        sleep=_SilentSleep(),
    )
    orch.start_session()
    # Swap to the failing source now that baseline is captured.
    orch._pnl_source = source  # type: ignore[attr-defined]
    exit_code = orch.run()

    assert orch.trigger_reason == "snapshot_source_down"
    assert exit_code == 1
    assert call_order == ["cancel_all", "flatten", "terminate"]
    assert source.calls >= 3


def test_request_stop_exits_cleanly_and_still_flattens(tmp_log: Path) -> None:
    source = _ScriptedPnLSource([_snap(0.0), _snap(0.5)])
    call_order: list[str] = []
    clock = _ScriptedClock(
        start=datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc),
        step=timedelta(seconds=10),
    )
    sleeper = _SilentSleep()

    def _sleep_then_stop(seconds: float) -> None:
        sleeper(seconds)
        orch.request_stop(reason="operator_sigint")

    orch = KillSwitchOrchestrator(
        pnl_source=source,
        config=KillSwitchConfig(threshold_usd=-5.0, poll_interval_seconds=10),
        cancel_all=lambda: (call_order.append("cancel_all"), {"ok": True})[1],
        flatten_positions=lambda: (call_order.append("flatten"), {"ok": True})[1],
        terminate_subprocess=lambda: call_order.append("terminate"),
        log_path=tmp_log,
        clock=clock,
        sleep=_sleep_then_stop,
    )
    orch.start_session()
    exit_code = orch.run()

    # request_stop fired before any trigger → clean exit code 0
    assert orch.triggered is False
    assert orch.trigger_reason == "operator_sigint"
    assert exit_code == 0
    # Flatten still ran (defence in depth).
    assert call_order == ["cancel_all", "flatten", "terminate"]


def test_log_file_is_one_json_object_per_line(tmp_log: Path) -> None:
    source = _ScriptedPnLSource([_snap(0.0), _snap(-6.0)])
    clock = _ScriptedClock(
        start=datetime(2026, 5, 18, 18, 0, tzinfo=timezone.utc),
        step=timedelta(seconds=10),
    )
    orch = KillSwitchOrchestrator(
        pnl_source=source,
        config=KillSwitchConfig(threshold_usd=-5.0, poll_interval_seconds=10),
        cancel_all=lambda: {"ok": True},
        flatten_positions=lambda: {"ok": True},
        terminate_subprocess=lambda: None,
        log_path=tmp_log,
        clock=clock,
        sleep=_SilentSleep(),
    )
    orch.start_session()
    orch.run()

    raw = tmp_log.read_text(encoding="utf-8").splitlines()
    assert raw, "log file should contain at least the session_started line"
    for line in raw:
        parsed = json.loads(line)
        # Every event must carry these mandatory fields.
        for key in ("at_iso", "kind", "cumulative_pnl_usd", "threshold_usd"):
            assert key in parsed, f"missing {key!r} in {line!r}"
    kinds = {json.loads(line)["kind"] for line in raw}
    assert "session_started" in kinds
    assert any(k.startswith("killswitch_triggered:") for k in kinds)


def test_killswitch_event_to_dict_roundtrip() -> None:
    ev = KillSwitchEvent(
        at_iso="2026-05-18T18:00:00Z",
        kind="snapshot",
        cumulative_pnl_usd=-1.2345678,
        threshold_usd=-5.0,
        note="hello",
        extra={"failure_streak": 0},
    )
    d = ev.to_dict()
    assert d["cumulative_pnl_usd"] == -1.2346  # rounded to 4 decimals
    assert d["threshold_usd"] == -5.0
    assert d["extra"] == {"failure_streak": 0}
