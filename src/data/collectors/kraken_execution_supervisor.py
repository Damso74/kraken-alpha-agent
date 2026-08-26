"""Bounded reconnect supervisor for the H-EXE-001 public collector.

Every connection is handled by a newly created collector instance.  Therefore
book/trade deltas cannot inherit sequence or book state across a transport gap;
fresh snapshots are mandatory.  The supervisor is local and contains no service
installation, authentication or order-entry code.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .kraken_execution_l2 import (
    ExecutionCollectorError,
    KrakenExecutionL2Collector,
    RecoverableConnectionError,
    run_public_shadow_stream,
)

CollectorFactory = Callable[[], KrakenExecutionL2Collector]


@dataclass(frozen=True)
class SupervisionResult:
    connections_started: int
    recoverable_connection_errors: tuple[str, ...]
    messages_received: int
    first_exchange_timestamp_ms: int | None
    last_exchange_timestamp_ms: int | None
    connection_windows: tuple[tuple[int, int], ...]


def run_supervised_shadow_once(
    collector_factory: CollectorFactory,
    *,
    duration_seconds: float,
    retry_delay_seconds: float = 1.0,
) -> SupervisionResult:
    """Run a bounded session and reconnect with brand-new collectors as needed."""
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds cannot be negative")
    deadline = time.monotonic() + duration_seconds
    connections = 0
    errors: list[str] = []
    total_messages = 0
    first_exchange_ms: int | None = None
    last_exchange_ms: int | None = None
    connection_windows: list[tuple[int, int]] = []

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        collector = collector_factory()
        connections += 1
        recoverable_failure = False
        try:
            total_messages += run_public_shadow_stream(
                collector, duration_seconds=max(0.01, remaining)
            )
        except RecoverableConnectionError as exc:
            recoverable_failure = True
            total_messages += exc.messages_received
            errors.append(str(exc))
        if collector.first_exchange_timestamp_ms is not None:
            first_exchange_ms = (
                collector.first_exchange_timestamp_ms
                if first_exchange_ms is None
                else min(first_exchange_ms, collector.first_exchange_timestamp_ms)
            )
        if collector.last_exchange_timestamp_ms is not None:
            last_exchange_ms = (
                collector.last_exchange_timestamp_ms
                if last_exchange_ms is None
                else max(last_exchange_ms, collector.last_exchange_timestamp_ms)
            )
        if (
            collector.first_exchange_timestamp_ms is not None
            and collector.last_exchange_timestamp_ms is not None
            and collector.last_exchange_timestamp_ms > collector.first_exchange_timestamp_ms
        ):
            connection_windows.append(
                (
                    collector.first_exchange_timestamp_ms,
                    collector.last_exchange_timestamp_ms,
                )
            )
        if time.monotonic() < deadline and recoverable_failure:
            time.sleep(min(retry_delay_seconds, max(0.0, deadline - time.monotonic())))
        else:
            break

    if total_messages == 0:
        raise ExecutionCollectorError("supervised public session ended without any message")
    return SupervisionResult(
        connections_started=connections,
        recoverable_connection_errors=tuple(errors),
        messages_received=total_messages,
        first_exchange_timestamp_ms=first_exchange_ms,
        last_exchange_timestamp_ms=last_exchange_ms,
        connection_windows=tuple(connection_windows),
    )
