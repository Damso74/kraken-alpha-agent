from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from src.research.ci_attestation import SAFETY_ENV, ci_scope_sha256
from src.research.execution_toxicity_ops import current_provenance, sha256_file
from src.research.execution_toxicity_validation import (
    CI_RECEIPT_SCHEMA,
    ci_receipt_path,
    evaluate_validation_journal,
)


def _write_gzip_jsonl(path: Path, rows: list[dict]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _seed_validation(output_root: Path, repo_root: Path) -> Path:
    provenance = current_provenance(repo_root)
    gate = {
        "schema_version": "h-exe-001-v1",
        "passed": True,
        "complete_utc_days": 14,
        "complete_day_list": [f"2026-01-{day:02d}" for day in range(1, 15)],
        "coverage_threshold": 0.99,
        "sequence_gaps": 0,
        "human_review_required": True,
        "authorizes_orders": False,
        "authorizes_validation_collection_only": True,
        **provenance,
    }
    gate_path = (
        output_root / "technical/ops/technical_gates/technical-gate-20260115T000000.000000Z.json"
    )
    gate_path.parent.mkdir(parents=True)
    gate_path.write_text(json.dumps(gate), encoding="utf-8")

    session_id = "validation-001"
    session_root = output_root / "validation/sessions" / session_id
    start = int(datetime(2026, 2, 1, tzinfo=UTC).timestamp() * 1000)
    end = start + int(86_400_000 * 0.995)

    def book(timestamp_ms: int, sequence: int, bid: float = 100, ask: float = 101) -> dict:
        return {
            "schema_version": "h-exe-001-v1",
            "event_type": "book_snapshot" if sequence == 1 else "book_delta",
            "product_id": "PF_XBTUSD",
            "connection_id": 1,
            "sequence": sequence,
            "exchange_timestamp_ms": timestamp_ms,
            "received_wall_ns": (timestamp_ms + 10) * 1_000_000,
            "received_monotonic_ns": timestamp_ms * 1_000_000,
            "observed_transport_lag_ms": 10.0,
            "bid": bid,
            "bid_qty": 10.0,
            "ask": ask,
            "ask_qty": 10.0,
            "mid": (bid + ask) / 2,
            "imbalance": 0.0,
        }

    raw_rows = [
        book(start + 1_000, 1),
        {
            "schema_version": "h-exe-001-v1",
            "event_type": "trade",
            "product_id": "PF_XBTUSD",
            "connection_id": 1,
            "sequence": 1,
            "exchange_timestamp_ms": start + 1_001,
            "received_wall_ns": (start + 1_011) * 1_000_000,
            "received_monotonic_ns": (start + 1_001) * 1_000_000,
            "observed_transport_lag_ms": 10.0,
            "snapshot": False,
            "side": "buy",
            "price": 101.0,
            "qty": 10.0,
        },
        book(start + 6_001, 2, bid=100.5, ask=101.5),
        book(start + 31_001, 3, bid=101, ask=102),
        book(start + 61_001, 4, bid=102, ask=103),
    ]
    observation = {
        "schema_version": "h-exe-001-v1",
        "event_type": "shadow_execution_observation",
        "exchange_timestamp_ms": start + 61_001,
        "probe_id": f"PF_XBTUSD-{start + 1_001}-1",
        "product_id": "PF_XBTUSD",
        "side": "buy",
        "route": "cross",
        "decision_timestamp_ms": start + 1_001,
        "completion_timestamp_ms": start + 61_001,
        "decision_transport_lag_ms": 10.0,
        "sweep_ratio": 1.0,
        "aligned_pressure": 1.0,
        "aligned_imbalance": 0.0,
        "toxicity_score": 2.0,
        "queue_ahead_qty": 10.0,
        "passive_traded_qty": 0.0,
        "passive_filled": False,
        "completed_within_horizon": True,
        "baseline_implementation_shortfall_bps": 59.75124378109541,
        "router_implementation_shortfall_bps": 59.75124378109541,
        "savings_bps": 0.0,
        "stress_savings_bps": -5.0,
        "markout_5s_bps": 49.75124378109541,
        "markout_30s_bps": 99.5024875621886,
        "markout_60s_bps": 199.0049751243772,
    }
    observation_file = _write_gzip_jsonl(
        session_root / "observations/2026-02-01/part-00000.jsonl.gz",
        [observation],
    )
    raw_file = _write_gzip_jsonl(
        session_root / "raw/2026-02-01/part-00000.jsonl.gz",
        raw_rows,
    )
    summary = {
        "schema_version": "h-exe-001-v1",
        "session_id": session_id,
        "phase": "validation",
        "preregistration": {"sha256": provenance["preregistration_sha256"]},
        "code_hashes": {
            key: value for key, value in provenance.items() if key != "preregistration_sha256"
        },
        "technical_gate": gate,
        "session": {
            "valid": True,
            "public_feeds_only": True,
            "credentials_used": False,
            "orders_sent": 0,
        },
        "collector": {
            "connection_windows": [[start, end]],
            "raw": {"rows_written": len(raw_rows), "files": [raw_file]},
            "observations": {"rows_written": 1, "files": [observation_file]},
        },
    }
    summary_path = session_root / "summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    journal = output_root / "validation/sessions.jsonl"
    journal.write_text(
        json.dumps(
            {
                "schema_version": "h-exe-001-session-journal-v1",
                "session_id": session_id,
                "phase": "validation",
                "summary_path": str(summary_path.resolve()),
                "summary_sha256": sha256_file(summary_path),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return Path(observation_file["path"])


def test_validation_journal_waits_for_technical_gate(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    report = evaluate_validation_journal(
        repo_root=repo_root,
        output_root=tmp_path,
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert report["status"] == "technical_gate_pending"
    assert report["decision"] == "NO-GO"
    assert report["safety"]["authorizes_paper_or_live"] is False


def test_validation_journal_verifies_hashes_coverage_and_observations(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    observation_path = _seed_validation(tmp_path, repo_root)
    report = evaluate_validation_journal(
        repo_root=repo_root,
        output_root=tmp_path,
        now=datetime(2026, 2, 3, tzinfo=UTC),
    )
    assert report["status"] == "collecting"
    assert report["sessions_verified"] is True
    assert report["complete_validation_utc_days"] == 1
    assert report["completed_probes"] == 1
    assert report["evaluation"]["gates"]["raw_replay_exact"] is True
    assert report["raw_replay_verified"] is True
    assert report["safety"]["orders_sent"] == 0

    with gzip.open(observation_path, "at", encoding="utf-8") as handle:
        handle.write("{}\n")
    tampered = evaluate_validation_journal(
        repo_root=repo_root,
        output_root=tmp_path,
        now=datetime(2026, 2, 3, tzinfo=UTC),
    )
    assert tampered["sessions_verified"] is False
    assert any("HASH_MISMATCH" in reason for reason in tampered["reason_codes"])


def test_validation_journal_accepts_only_source_bound_ci_receipt(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    _seed_validation(tmp_path, repo_root)
    provenance = current_provenance(repo_root)
    scope_sha256, scope_files = ci_scope_sha256(repo_root)
    receipt = ci_receipt_path(tmp_path, provenance)
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "schema_version": CI_RECEIPT_SCHEMA,
                "source_hashes": provenance,
                "ci_scope_sha256": scope_sha256,
                "ci_scope_tracked_files": scope_files,
                "ruff_scope": "src tests scripts",
                "ruff_passed": True,
                "bash_syntax_scope": "scripts/*.sh",
                "bash_syntax_passed": True,
                "shellcheck_scope": "shellcheck -S error scripts/*.sh",
                "shellcheck_passed": True,
                "pytest_collected": 1,
                "pytest_passed": True,
                "git_diff_clean": True,
                "git_status_clean": True,
                "safety_env": SAFETY_ENV,
            }
        ),
        encoding="utf-8",
    )
    report = evaluate_validation_journal(
        repo_root=repo_root,
        output_root=tmp_path,
        now=datetime(2026, 2, 3, tzinfo=UTC),
    )
    assert report["ci"]["verified"] is True
    assert report["evaluation"]["gates"]["ci_scope_verified"] is True

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["ci_scope_sha256"] = "0" * 64
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    scope_tampered = evaluate_validation_journal(
        repo_root=repo_root,
        output_root=tmp_path,
        now=datetime(2026, 2, 3, tzinfo=UTC),
    )
    assert scope_tampered["ci"]["verified"] is False

    payload["ci_scope_sha256"] = scope_sha256
    payload["source_hashes"] = {**provenance, "engine_sha256": "0" * 64}
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    tampered = evaluate_validation_journal(
        repo_root=repo_root,
        output_root=tmp_path,
        now=datetime(2026, 2, 3, tzinfo=UTC),
    )
    assert tampered["ci"]["verified"] is False
