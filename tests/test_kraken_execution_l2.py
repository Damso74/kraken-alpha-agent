from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from src.data.collectors.kraken_execution_l2 import (
    ExecutionCollectorError,
    GlobalStorageBudget,
    KrakenExecutionL2Collector,
    RotatingGzipJsonlWriter,
    SequenceGapError,
    StorageCapExceeded,
)


def _snapshot(seq: int = 10, timestamp: int = 1_700_000_000_000) -> dict:
    return {
        "feed": "book_snapshot",
        "product_id": "PF_XBTUSD",
        "seq": seq,
        "timestamp": timestamp,
        "bids": [{"price": 100, "qty": 10}, {"price": 99, "qty": 20}],
        "asks": [{"price": 101, "qty": 12}, {"price": 102, "qty": 25}],
    }


def test_book_snapshot_and_contiguous_delta_are_normalized() -> None:
    collector = KrakenExecutionL2Collector(["PF_XBTUSD"])
    snapshot_events = collector.process_message(
        _snapshot(),
        received_wall_ns=1_700_000_000_010_000_000,
        received_monotonic_ns=123,
    )
    assert len(snapshot_events) == 1
    assert snapshot_events[0]["mid"] == pytest.approx(100.5)
    assert snapshot_events[0]["bid_depth"] == pytest.approx(30)
    assert snapshot_events[0]["received_monotonic_ns"] == 123

    events = collector.process_message(
        {
            "feed": "book",
            "product_id": "PF_XBTUSD",
            "seq": 11,
            "timestamp": 1_700_000_000_001,
            "side": "buy",
            "price": 100,
            "qty": 7,
        },
        received_wall_ns=1_700_000_000_020_000_000,
        received_monotonic_ns=456,
    )
    assert events[0]["event_type"] == "book_delta"
    assert events[0]["bid_qty"] == pytest.approx(7)
    assert events[0]["sequence"] == 11


def test_sequence_gap_invalidates_session_fail_closed() -> None:
    collector = KrakenExecutionL2Collector(["PF_XBTUSD"])
    collector.process_message(_snapshot(seq=40))
    with pytest.raises(SequenceGapError, match="expected 41, got 42"):
        collector.process_message(
            {
                "feed": "book",
                "product_id": "PF_XBTUSD",
                "seq": 42,
                "timestamp": 1_700_000_000_001,
                "side": "sell",
                "price": 101,
                "qty": 11,
            }
        )
    assert collector.valid is False
    with pytest.raises(ExecutionCollectorError, match="session is invalid"):
        collector.process_message(_snapshot(seq=50))


def test_delta_before_snapshot_is_rejected() -> None:
    collector = KrakenExecutionL2Collector(["PF_XBTUSD"])
    with pytest.raises(SequenceGapError, match="before snapshot"):
        collector.process_message(
            {
                "feed": "book",
                "product_id": "PF_XBTUSD",
                "seq": 1,
                "timestamp": 1_700_000_000_001,
                "side": "buy",
                "price": 100,
                "qty": 1,
            }
        )


def test_reconnect_requires_fresh_snapshot_and_invokes_reset_handler() -> None:
    resets: list[str] = []
    collector = KrakenExecutionL2Collector(
        ["PF_XBTUSD"], on_connection_reset=lambda: resets.append("reset")
    )
    collector.process_message(_snapshot(seq=10))
    collector.begin_connection()
    assert resets == ["reset"]
    with pytest.raises(SequenceGapError, match="before snapshot"):
        collector.process_message(
            {
                "feed": "book",
                "product_id": "PF_XBTUSD",
                "seq": 11,
                "timestamp": 1_700_000_000_001,
                "side": "buy",
                "price": 100,
                "qty": 1,
            }
        )


def test_trade_snapshot_sets_high_watermark_then_requires_next_sequence() -> None:
    collector = KrakenExecutionL2Collector(["PF_XBTUSD"])
    events = collector.process_message(
        {
            "feed": "trade_snapshot",
            "product_id": "PF_XBTUSD",
            "trades": [
                {
                    "seq": 8,
                    "time": 1_700_000_000_008,
                    "uid": "b",
                    "side": "buy",
                    "type": "fill",
                    "price": 101,
                    "qty": 2,
                },
                {
                    "seq": 7,
                    "time": 1_700_000_000_007,
                    "uid": "a",
                    "side": "sell",
                    "type": "fill",
                    "price": 100,
                    "qty": 1,
                },
            ],
        }
    )
    assert [event["sequence"] for event in events] == [7, 8]
    assert all(event["snapshot"] for event in events)
    delta = collector.process_message(
        {
            "feed": "trade",
            "product_id": "PF_XBTUSD",
            "seq": 9,
            "time": 1_700_000_000_009,
            "uid": "c",
            "side": "buy",
            "type": "fill",
            "price": 101,
            "qty": 3,
        }
    )
    assert delta[0]["snapshot"] is False


def test_control_frames_are_ignored_and_subscriptions_are_public() -> None:
    collector = KrakenExecutionL2Collector(["PF_XBTUSD", "PF_ETHUSD"])
    assert collector.process_message({"event": "subscribed", "feed": "book"}) == []
    subscriptions = collector.subscriptions()
    assert {item["feed"] for item in subscriptions} == {"book", "trade"}
    assert all("api_key" not in json.dumps(item) for item in subscriptions)


def test_rotating_writer_creates_readable_gzip_parts_and_manifest(tmp_path: Path) -> None:
    writer = RotatingGzipJsonlWriter(
        tmp_path,
        max_file_bytes=220,
        storage_cap_bytes=10_000,
    )
    for index in range(4):
        writer.append(
            {
                "exchange_timestamp_ms": 1_700_000_000_000 + index,
                "event_type": "book_delta",
                "payload": "x" * 80,
            }
        )
    manifest = writer.manifest()
    assert manifest["rows_written"] == 4
    assert len(manifest["files"]) >= 2
    rows = []
    for file_info in manifest["files"]:
        with gzip.open(file_info["path"], mode="rt", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle)
        assert len(file_info["sha256"]) == 64
    assert len(rows) == 4


def test_storage_cap_stops_before_write_without_deleting(tmp_path: Path) -> None:
    existing = tmp_path / "existing.bin"
    existing.write_bytes(b"z" * 180)
    writer = RotatingGzipJsonlWriter(
        tmp_path,
        max_file_bytes=200,
        storage_cap_bytes=200,
    )
    with pytest.raises(StorageCapExceeded, match="exceed global storage cap"):
        writer.append(
            {
                "exchange_timestamp_ms": 1_700_000_000_000,
                "payload": "would exceed",
            }
        )
    assert existing.read_bytes() == b"z" * 180


def test_global_budget_is_shared_between_raw_and_observation_writers(tmp_path: Path) -> None:
    budget = GlobalStorageBudget(tmp_path, storage_cap_bytes=320)
    raw = RotatingGzipJsonlWriter(
        tmp_path / "session" / "raw",
        max_file_bytes=320,
        storage_cap_bytes=320,
        storage_budget=budget,
    )
    observations = RotatingGzipJsonlWriter(
        tmp_path / "session" / "observations",
        max_file_bytes=320,
        storage_cap_bytes=320,
        storage_budget=budget,
    )
    raw.append({"exchange_timestamp_ms": 1_700_000_000_000, "payload": "r" * 100})
    with pytest.raises(StorageCapExceeded, match="global storage cap"):
        observations.append(
            {"exchange_timestamp_ms": 1_700_000_000_001, "payload": "o" * 200}
        )
    raw.close()
    observations.close()


def test_new_session_budget_counts_files_from_previous_sessions(tmp_path: Path) -> None:
    previous = tmp_path / "technical" / "sessions" / "old" / "raw.bin"
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b"x" * 290)
    budget = GlobalStorageBudget(tmp_path, storage_cap_bytes=320)
    writer = RotatingGzipJsonlWriter(
        tmp_path / "technical" / "sessions" / "new" / "raw",
        max_file_bytes=320,
        storage_cap_bytes=320,
        storage_budget=budget,
    )
    with pytest.raises(StorageCapExceeded, match="global storage cap"):
        writer.append({"exchange_timestamp_ms": 1_700_000_000_000, "payload": "new"})
