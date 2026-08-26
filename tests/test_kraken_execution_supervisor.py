from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.data.collectors.kraken_execution_l2 import (
    KrakenExecutionL2Collector,
    RecoverableConnectionError,
)
from src.data.collectors.kraken_execution_supervisor import run_supervised_shadow_once


def test_supervisor_recreates_collector_after_recoverable_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[KrakenExecutionL2Collector] = []

    def factory() -> KrakenExecutionL2Collector:
        collector = KrakenExecutionL2Collector(["PF_XBTUSD"])
        created.append(collector)
        return collector

    outcomes: Iterator[object] = iter(
        [RecoverableConnectionError("closed", messages_received=3), 4]
    )

    def fake_stream(collector: KrakenExecutionL2Collector, *, duration_seconds: float) -> int:
        assert duration_seconds > 0
        result = next(outcomes)
        if isinstance(result, Exception):
            collector.first_exchange_timestamp_ms = 100
            collector.last_exchange_timestamp_ms = 200
            raise result
        collector.first_exchange_timestamp_ms = 300
        collector.last_exchange_timestamp_ms = 400
        return int(result)

    monkeypatch.setattr(
        "src.data.collectors.kraken_execution_supervisor.run_public_shadow_stream",
        fake_stream,
    )
    monkeypatch.setattr(
        "src.data.collectors.kraken_execution_supervisor.time.sleep", lambda _seconds: None
    )
    result = run_supervised_shadow_once(
        factory, duration_seconds=1.0, retry_delay_seconds=0
    )
    assert len(created) == 2
    assert created[0] is not created[1]
    assert result.messages_received == 7
    assert result.connections_started == 2
    assert result.first_exchange_timestamp_ms == 100
    assert result.last_exchange_timestamp_ms == 400
    assert result.connection_windows == ((100, 200), (300, 400))
