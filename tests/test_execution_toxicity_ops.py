from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.run_execution_toxicity_ops_once import collection_phase
from scripts.run_execution_toxicity_shadow import ProgressHeartbeat
from src.data.collectors.kraken_execution_l2 import GlobalStorageBudget
from src.research.execution_toxicity_ops import (
    DAY_MS,
    aggregate_technical_health,
    current_provenance,
    sha256_file,
    technical_gate_payload,
)


def _write_session(
    *,
    repo_root: Path,
    output_root: Path,
    day: datetime,
    session_id: str,
    valid: bool = True,
) -> None:
    provenance = current_provenance(repo_root)
    phase_root = output_root / "technical"
    session_root = phase_root / "sessions" / session_id
    session_root.mkdir(parents=True, exist_ok=True)
    start_ms = int(day.timestamp() * 1000)
    end_ms = start_ms + int(DAY_MS * 0.995)
    code_hashes = {
        key: value for key, value in provenance.items() if key != "preregistration_sha256"
    }
    summary = {
        "schema_version": "h-exe-001-v1",
        "session_id": session_id,
        "preregistration": {"sha256": provenance["preregistration_sha256"]},
        "code_hashes": code_hashes,
        "session": {"valid": valid, "invalid_reason": None if valid else "failure"},
        "collector": {
            "first_exchange_timestamp_ms": start_ms,
            "last_exchange_timestamp_ms": end_ms,
            "connection_error_count": 0,
            "connection_windows": [[start_ms, end_ms]],
        },
        "engine_counts": {
            "PF_XBTUSD": {"discarded_pending_on_reset": 0},
            "PF_ETHUSD": {"discarded_pending_on_reset": 0},
        },
    }
    summary_path = session_root / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    row = {
        "schema_version": "h-exe-001-session-journal-v1",
        "session_id": session_id,
        "summary_path": str(summary_path.resolve()),
        "summary_sha256": sha256_file(summary_path),
        "valid": valid,
        "first_exchange_timestamp_ms": start_ms,
        "last_exchange_timestamp_ms": end_ms,
        **provenance,
    }
    journal = phase_root / "sessions.jsonl"
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def test_health_issues_gate_only_after_fourteen_complete_days(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    first_day = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(14):
        _write_session(
            repo_root=repo_root,
            output_root=tmp_path,
            day=first_day + timedelta(days=index),
            session_id=f"session-{index:02d}",
        )
    health = aggregate_technical_health(
        repo_root=repo_root,
        output_root=tmp_path,
        now=datetime(2026, 1, 16, tzinfo=UTC),
    )
    assert health["passed"] is True
    assert health["complete_utc_days"] == 14
    gate = technical_gate_payload(health)
    assert gate["passed"] is True
    assert gate["sequence_gaps"] == 0
    assert gate["authorizes_orders"] is False


def test_health_fails_closed_on_tampered_summary(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    _write_session(
        repo_root=repo_root,
        output_root=tmp_path,
        day=datetime(2026, 1, 1, tzinfo=UTC),
        session_id="session-tampered",
    )
    summary = next((tmp_path / "technical" / "sessions").rglob("summary.json"))
    summary.write_text("{}", encoding="utf-8")
    health = aggregate_technical_health(
        repo_root=repo_root,
        output_root=tmp_path,
        now=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert health["passed"] is False
    assert "SESSION_SUMMARY_HASH_MISMATCH" in health["reason_codes"]


def test_health_fails_with_less_than_fourteen_days(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    _write_session(
        repo_root=repo_root,
        output_root=tmp_path,
        day=datetime(2026, 1, 1, tzinfo=UTC),
        session_id="session-one",
    )
    health = aggregate_technical_health(
        repo_root=repo_root,
        output_root=tmp_path,
        now=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert health["passed"] is False
    assert "FEWER_THAN_14_COMPLETE_UTC_DAYS" in health["reason_codes"]


def test_progress_heartbeat_is_atomic_and_tracks_only_observed_events(
    tmp_path: Path,
) -> None:
    budget = GlobalStorageBudget(tmp_path, storage_cap_bytes=10_000)
    heartbeat = ProgressHeartbeat(
        tmp_path / "session" / "progress.json",
        session_id="session-progress",
        storage_budget=budget,
        interval_ns=5_000_000_000,
    )
    heartbeat.observe(
        {
            "exchange_timestamp_ms": 1_700_000_000_000,
            "received_wall_ns": 1_700_000_000_100_000_000,
            "received_monotonic_ns": 10_000_000_000,
        }
    )
    heartbeat.observe(
        {
            "exchange_timestamp_ms": 1_700_000_001_000,
            "received_wall_ns": 1_700_000_001_100_000_000,
            "received_monotonic_ns": 11_000_000_000,
        }
    )
    heartbeat.finalize()
    payload = json.loads((tmp_path / "session" / "progress.json").read_text())
    assert payload["event_count"] == 2
    assert payload["last_exchange_timestamp_ms"] == 1_700_000_001_000
    assert payload["credentials_used"] is False
    assert payload["orders_sent"] == 0
    assert not list(tmp_path.rglob("*.tmp"))
    manifest = heartbeat.manifest()
    assert manifest is not None
    assert len(manifest["sha256"]) == 64


def test_ops_phase_switches_only_after_immutable_technical_gate(tmp_path: Path) -> None:
    assert collection_phase(tmp_path) == ("technical", None)
    gate_root = tmp_path / "technical/ops/technical_gates"
    gate_root.mkdir(parents=True)
    older = gate_root / "technical-gate-20260101T000000.000000Z.json"
    newer = gate_root / "technical-gate-20260102T000000.000000Z.json"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    phase, selected = collection_phase(tmp_path)
    assert phase == "validation"
    assert selected == newer
