"""Library backing the live-session kill switch.

The kill switch is a *supervisor* process: it spawns the regular agent
loop in a child subprocess, then independently polls a PnL source
every ``poll_interval_seconds``. The moment the cumulative session
PnL (relative to the snapshot taken at startup) drops to or below a
configurable threshold (default ``-5.00 USD``), the supervisor:

1. cancels every open order on the futures venue,
2. issues a ``reduce-only`` market sell on every open long,
3. terminates the child subprocess,
4. records the event to a structured log file, and
5. exits with status ``1``.

Soft cutoffs also fire on:

- the user requested ``--max-duration-hours`` ceiling,
- the configured CEST flatten cut-off (default ``21:55``),
- ``SIGINT`` / ``SIGTERM`` from the operator.

This module is intentionally side-effect free: the PnL source,
the cancel-all callback, the flatten callback, the subprocess
terminator, and the wall-clock are all injectable so the suite
can exercise every branch deterministically without ever touching
Kraken.

Hard safety contract
--------------------
- This module does **not** import :mod:`src.execution` and never
  shells out to Kraken on its own. Every venue-mutating side-effect
  flows through callables provided by the caller, which is the
  only place the production wiring lives.
- The kill-switch decision is monotonic: once ``triggered`` becomes
  ``True`` the orchestrator never goes back to a non-triggered state,
  no matter what subsequent snapshots look like. This is paranoid by
  design — we never want a transient API blip to "un-fire" the
  switch.
- The threshold is interpreted in **USD, negative**: a value of
  ``-5.0`` means "stop when cumulative PnL ≤ −5.00 USD". Positive
  thresholds are clamped to ``-0.01`` so an operator typo cannot
  accidentally disable the switch.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PnLSnapshot:
    """Minimal PnL reading consumed by the kill-switch loop."""

    realized_usd: float
    unrealized_usd: float
    at_iso: str
    source: str = "kraken_futures_accounts"
    raw: dict | None = None

    @property
    def net_usd(self) -> float:
        return float(self.realized_usd) + float(self.unrealized_usd)


class PnLSource(Protocol):
    """Anything that can produce a fresh :class:`PnLSnapshot` on demand."""

    def snapshot(self) -> PnLSnapshot: ...


@dataclass
class KillSwitchEvent:
    """One structured record appended to the kill-switch log."""

    at_iso: str
    kind: str          # e.g. "session_started", "snapshot", "killswitch_triggered"
    cumulative_pnl_usd: float = 0.0
    baseline_realized_usd: float = 0.0
    baseline_unrealized_usd: float = 0.0
    threshold_usd: float = 0.0
    note: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "at_iso": self.at_iso,
            "kind": self.kind,
            "cumulative_pnl_usd": round(self.cumulative_pnl_usd, 4),
            "baseline_realized_usd": round(self.baseline_realized_usd, 4),
            "baseline_unrealized_usd": round(self.baseline_unrealized_usd, 4),
            "threshold_usd": round(self.threshold_usd, 4),
            "note": self.note,
            "extra": self.extra,
        }


@dataclass
class KillSwitchConfig:
    """Tunable thresholds. Defaults match the option-D activation brief."""

    threshold_usd: float = -5.0           # hard stop (cumulative ≤ this)
    poll_interval_seconds: float = 10.0
    max_duration_seconds: float = 24 * 3600.0
    flatten_cest_hour: int = 21
    flatten_cest_minute: int = 55
    snapshot_failure_limit: int = 5       # consecutive fetch failures before
                                          # we treat the source as down

    def __post_init__(self) -> None:
        # Paranoid clamps. The threshold is meaningful only when ≤ 0; we
        # round up to -0.01 if the operator passes a positive value
        # (typo guard).
        self.threshold_usd = float(self.threshold_usd)
        if self.threshold_usd > -1e-9:
            self.threshold_usd = -0.01
        self.poll_interval_seconds = max(1.0, float(self.poll_interval_seconds))
        self.max_duration_seconds = max(60.0, float(self.max_duration_seconds))
        self.snapshot_failure_limit = max(1, int(self.snapshot_failure_limit))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CEST_OFFSET_SECONDS = 2 * 3600  # CEST = UTC+2; used as a fixed mapping here.


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def cest_cutoff_reached(
    now_utc: datetime,
    *,
    hour: int,
    minute: int,
) -> bool:
    """Return ``True`` once the CEST wall clock reaches the cut-off.

    Uses a fixed UTC+2 offset so the function is deterministic regardless
    of the host's local timezone configuration. The user runs this from
    France during the hackathon (CEST in May 2026), so the offset is
    locked.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    cest_now = now_utc.timestamp() + _CEST_OFFSET_SECONDS
    cest_dt = datetime.fromtimestamp(cest_now, tz=UTC)
    cutoff_minutes = hour * 60 + minute
    now_minutes = cest_dt.hour * 60 + cest_dt.minute
    return now_minutes >= cutoff_minutes


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class KillSwitchOrchestrator:
    """Drive the polling loop and decide when to fire the switch.

    The orchestrator owns no I/O — every side effect (PnL polling,
    cancel-all, flatten, subprocess kill, wall-clock, sleep) is
    injected. This lets the test suite walk through every branch
    deterministically and lets the production script wire real
    Kraken calls without touching the decision logic.
    """

    def __init__(
        self,
        *,
        pnl_source: PnLSource,
        config: KillSwitchConfig,
        cancel_all: Callable[[], dict],
        flatten_positions: Callable[[], dict],
        terminate_subprocess: Callable[[], None],
        log_path: Path | None = None,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._pnl_source = pnl_source
        self._config = config
        self._cancel_all = cancel_all
        self._flatten_positions = flatten_positions
        self._terminate = terminate_subprocess
        self._log_path = log_path
        self._clock = clock
        self._sleep = sleep
        self._stop_event = threading.Event()
        self._baseline: PnLSnapshot | None = None
        self._latest: PnLSnapshot | None = None
        self._triggered: bool = False
        self._trigger_reason: str = ""
        self._failure_streak: int = 0
        self._started_at: datetime | None = None

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def triggered(self) -> bool:
        return self._triggered

    @property
    def trigger_reason(self) -> str:
        return self._trigger_reason

    @property
    def baseline(self) -> PnLSnapshot | None:
        return self._baseline

    @property
    def latest_snapshot(self) -> PnLSnapshot | None:
        return self._latest

    def cumulative_pnl_usd(self) -> float:
        if self._baseline is None or self._latest is None:
            return 0.0
        return self._latest.net_usd - self._baseline.net_usd

    def request_stop(self, *, reason: str = "external_stop") -> None:
        """Politely ask the loop to exit at its next iteration."""
        self._stop_event.set()
        if not self._trigger_reason:
            self._trigger_reason = reason

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_session(self) -> KillSwitchEvent:
        """Capture the baseline snapshot. Must be called once at startup."""
        snap = self._pnl_source.snapshot()
        self._baseline = snap
        self._latest = snap
        self._started_at = self._clock()
        event = KillSwitchEvent(
            at_iso=iso(self._started_at),
            kind="session_started",
            cumulative_pnl_usd=0.0,
            baseline_realized_usd=snap.realized_usd,
            baseline_unrealized_usd=snap.unrealized_usd,
            threshold_usd=self._config.threshold_usd,
            note=(
                f"baseline pnl={snap.net_usd:+.4f}USD "
                f"threshold={self._config.threshold_usd:+.2f}USD "
                f"poll={self._config.poll_interval_seconds:.0f}s"
            ),
            extra={"source": snap.source},
        )
        self._append_event(event)
        return event

    def run(self) -> int:
        """Block on the polling loop until a trigger fires.

        Returns the process exit code (``0`` for a clean stop, ``1``
        for a kill-switch trigger).
        """
        assert self._started_at is not None, "call start_session() first"
        deadline = self._started_at + _seconds_to_timedelta(
            self._config.max_duration_seconds
        )

        while not self._stop_event.is_set():
            now = self._clock()
            # 1) Time-based stops -----------------------------------
            if now >= deadline:
                self._trigger("max_duration_reached", note="max-duration deadline reached")
                break
            if cest_cutoff_reached(
                now,
                hour=self._config.flatten_cest_hour,
                minute=self._config.flatten_cest_minute,
            ):
                self._trigger(
                    "cest_cutoff",
                    note=(
                        f"CEST cut-off {self._config.flatten_cest_hour:02d}:"
                        f"{self._config.flatten_cest_minute:02d} reached"
                    ),
                )
                break

            # 2) PnL snapshot ----------------------------------------
            try:
                snap = self._pnl_source.snapshot()
                self._failure_streak = 0
            except Exception as exc:  # noqa: BLE001
                self._failure_streak += 1
                self._append_event(
                    KillSwitchEvent(
                        at_iso=iso(now),
                        kind="snapshot_error",
                        cumulative_pnl_usd=self.cumulative_pnl_usd(),
                        baseline_realized_usd=(
                            self._baseline.realized_usd if self._baseline else 0.0
                        ),
                        baseline_unrealized_usd=(
                            self._baseline.unrealized_usd if self._baseline else 0.0
                        ),
                        threshold_usd=self._config.threshold_usd,
                        note=f"snapshot fetch failed: {exc!r}",
                        extra={"failure_streak": self._failure_streak},
                    )
                )
                if self._failure_streak >= self._config.snapshot_failure_limit:
                    self._trigger(
                        "snapshot_source_down",
                        note=(
                            f"{self._failure_streak} consecutive snapshot "
                            "failures — flattening conservatively"
                        ),
                    )
                    break
                self._sleep(self._config.poll_interval_seconds)
                continue
            self._latest = snap
            cumulative = self.cumulative_pnl_usd()
            self._append_event(
                KillSwitchEvent(
                    at_iso=iso(now),
                    kind="snapshot",
                    cumulative_pnl_usd=cumulative,
                    baseline_realized_usd=(
                        self._baseline.realized_usd if self._baseline else 0.0
                    ),
                    baseline_unrealized_usd=(
                        self._baseline.unrealized_usd if self._baseline else 0.0
                    ),
                    threshold_usd=self._config.threshold_usd,
                    note=(
                        f"realized={snap.realized_usd:+.4f} "
                        f"unrealized={snap.unrealized_usd:+.4f} "
                        f"net={snap.net_usd:+.4f}"
                    ),
                    extra={"source": snap.source},
                )
            )

            # 3) Hard kill condition --------------------------------
            if cumulative <= self._config.threshold_usd + 1e-9:
                self._trigger(
                    "killswitch_pnl",
                    note=(
                        f"cumulative PnL {cumulative:+.4f}USD breached "
                        f"threshold {self._config.threshold_usd:+.2f}USD"
                    ),
                )
                break

            # 4) Wait then loop -------------------------------------
            self._sleep(self._config.poll_interval_seconds)

        if self._triggered:
            self._execute_flatten()
            return 1
        # Clean exit (e.g. stop_event from SIGINT before any trigger).
        # We still flatten because we never want to leave open positions
        # behind us at shutdown.
        self._execute_flatten(label="clean_stop")
        return 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _trigger(self, kind: str, *, note: str) -> None:
        if self._triggered:
            return
        self._triggered = True
        self._trigger_reason = kind
        now = self._clock()
        self._append_event(
            KillSwitchEvent(
                at_iso=iso(now),
                kind=f"killswitch_triggered:{kind}",
                cumulative_pnl_usd=self.cumulative_pnl_usd(),
                baseline_realized_usd=(
                    self._baseline.realized_usd if self._baseline else 0.0
                ),
                baseline_unrealized_usd=(
                    self._baseline.unrealized_usd if self._baseline else 0.0
                ),
                threshold_usd=self._config.threshold_usd,
                note=note,
            )
        )

    def _execute_flatten(self, *, label: str = "trigger") -> None:
        try:
            cancel_result = self._cancel_all()
        except Exception as exc:  # noqa: BLE001
            cancel_result = {"ok": False, "error": repr(exc)}
        try:
            flatten_result = self._flatten_positions()
        except Exception as exc:  # noqa: BLE001
            flatten_result = {"ok": False, "error": repr(exc)}
        try:
            self._terminate()
            terminated = True
        except Exception as exc:  # noqa: BLE001
            terminated = False
            self._append_event(
                KillSwitchEvent(
                    at_iso=iso(self._clock()),
                    kind="subprocess_terminate_failed",
                    threshold_usd=self._config.threshold_usd,
                    note=repr(exc),
                )
            )
        self._append_event(
            KillSwitchEvent(
                at_iso=iso(self._clock()),
                kind=f"flatten_complete:{label}",
                cumulative_pnl_usd=self.cumulative_pnl_usd(),
                baseline_realized_usd=(
                    self._baseline.realized_usd if self._baseline else 0.0
                ),
                baseline_unrealized_usd=(
                    self._baseline.unrealized_usd if self._baseline else 0.0
                ),
                threshold_usd=self._config.threshold_usd,
                note="venue flatten + subprocess kill complete",
                extra={
                    "cancel_all": cancel_result,
                    "flatten_positions": flatten_result,
                    "subprocess_terminated": terminated,
                },
            )
        )

    def _append_event(self, event: KillSwitchEvent) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), default=str) + "\n")
        except OSError:
            # Logging must never tank the kill switch.
            pass


def _seconds_to_timedelta(seconds: float):
    from datetime import timedelta

    return timedelta(seconds=float(seconds))


__all__ = [
    "PnLSnapshot",
    "PnLSource",
    "KillSwitchEvent",
    "KillSwitchConfig",
    "KillSwitchOrchestrator",
    "cest_cutoff_reached",
    "iso",
    "utc_now",
]
