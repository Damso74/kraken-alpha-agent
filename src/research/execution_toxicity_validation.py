"""Verified multi-session validation journal for H-EXE-001.

The module is read-only.  It verifies immutable summaries, raw/observation
manifests, source hashes, safety invariants and UTC coverage before delegating
economic metrics to :mod:`src.research.execution_toxicity`.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .ci_attestation import validate_ci_evidence
from .execution_toxicity import (
    CompletedProbe,
    ExecutionToxicityShadow,
    evaluate_validation_evidence,
)
from .execution_toxicity_ops import (
    COMPLETE_DAY_COVERAGE,
    DAY_MS,
    _merged_coverage_ms,
    _split_interval_by_day,
    aggregate_technical_health,
    current_provenance,
    read_session_journal,
    sha256_file,
)

SCHEMA_VERSION = "h-exe-001-validation-journal-v1"
CI_RECEIPT_SCHEMA = "h-exe-001-ci-receipt-v1"


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def ci_receipt_path(output_root: Path, source_hashes: dict[str, str]) -> Path:
    return (
        Path(output_root)
        / "validation/ops/evaluations/ci_receipts"
        / f"ci-{_canonical_sha256(source_hashes)}.json"
    )


def _ci_receipt_valid(
    output_root: Path, source_hashes: dict[str, str], repo_root: Path
) -> tuple[bool, list[str], Path]:
    path = ci_receipt_path(output_root, source_hashes)
    if not path.is_file():
        return False, ["CI_RECEIPT_MISSING"], path
    try:
        payload = _load_json(path)
    except ValueError:
        return False, ["CI_RECEIPT_INVALID_JSON"], path
    reasons: list[str] = []
    if payload.get("schema_version") != CI_RECEIPT_SCHEMA:
        reasons.append("CI_RECEIPT_SCHEMA_MISMATCH")
    if payload.get("source_hashes") != source_hashes:
        reasons.append("CI_RECEIPT_SOURCE_HASH_MISMATCH")
    reasons.extend(validate_ci_evidence(payload, repo_root))
    return not reasons, reasons, path


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return payload


def _probe_from_record(record: dict[str, Any]) -> CompletedProbe:
    if (
        record.get("schema_version") != "h-exe-001-v1"
        or record.get("event_type") != "shadow_execution_observation"
    ):
        raise ValueError("invalid H-EXE observation envelope")
    names = {field.name for field in fields(CompletedProbe)}
    if any(name not in record for name in names):
        raise ValueError("H-EXE observation fields are incomplete")
    probe = CompletedProbe(**{name: record[name] for name in names})
    if probe.side not in {"buy", "sell"} or probe.route not in {"cross", "passive"}:
        raise ValueError("invalid H-EXE observation enum")
    if not isinstance(probe.passive_filled, bool) or not isinstance(
        probe.completed_within_horizon, bool
    ):
        raise ValueError("invalid H-EXE observation booleans")
    if (
        isinstance(probe.decision_timestamp_ms, bool)
        or not isinstance(probe.decision_timestamp_ms, int)
        or isinstance(probe.completion_timestamp_ms, bool)
        or not isinstance(probe.completion_timestamp_ms, int)
        or probe.completion_timestamp_ms < probe.decision_timestamp_ms + 60_000
    ):
        raise ValueError("invalid H-EXE observation timestamps")
    numeric = (
        probe.decision_transport_lag_ms,
        probe.sweep_ratio,
        probe.aligned_pressure,
        probe.aligned_imbalance,
        probe.toxicity_score,
        probe.queue_ahead_qty,
        probe.passive_traded_qty,
        probe.baseline_implementation_shortfall_bps,
        probe.router_implementation_shortfall_bps,
        probe.savings_bps,
        probe.stress_savings_bps,
        probe.markout_5s_bps,
        probe.markout_30s_bps,
        probe.markout_60s_bps,
    )
    if not all(math.isfinite(float(value)) for value in numeric):
        raise ValueError("non-finite H-EXE observation metric")
    return probe


def _verified_manifest_files(
    manifest: Any, *, phase_root: Path, label: str
) -> tuple[list[Path], list[str]]:
    errors: list[str] = []
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        return [], [f"{label}_MANIFEST_INVALID"]
    paths: list[Path] = []
    for item in manifest["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            errors.append(f"{label}_FILE_RECORD_INVALID")
            continue
        path = Path(item["path"])
        if not _inside(path, phase_root):
            errors.append(f"{label}_FILE_OUTSIDE_VALIDATION_ROOT")
            continue
        if not path.is_file():
            errors.append(f"{label}_FILE_MISSING")
            continue
        if sha256_file(path) != item.get("sha256"):
            errors.append(f"{label}_FILE_HASH_MISMATCH")
            continue
        if path.stat().st_size != item.get("bytes"):
            errors.append(f"{label}_FILE_SIZE_MISMATCH")
            continue
        paths.append(path)
    return paths, errors


def _read_gzip_records(paths: list[Path], *, label: str) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            raise ValueError("record is not an object")
                        records.append(record)
                    except (json.JSONDecodeError, TypeError, ValueError) as exc:
                        errors.append(f"{label}_INVALID:{path.name}:{line_number}:{exc}")
        except (OSError, EOFError) as exc:
            errors.append(f"{label}_GZIP_INVALID:{path.name}:{exc}")
    return records, errors


def _read_observations(
    paths: list[Path],
) -> tuple[list[CompletedProbe], list[dict[str, Any]], list[str]]:
    probes: list[CompletedProbe] = []
    records, errors = _read_gzip_records(paths, label="OBSERVATION")
    for index, record in enumerate(records, start=1):
        try:
            probes.append(_probe_from_record(record))
        except (TypeError, ValueError) as exc:
            errors.append(f"OBSERVATION_INVALID:record-{index}:{exc}")
    return probes, records, errors


def _observation_record(probe: CompletedProbe) -> dict[str, Any]:
    return {
        "schema_version": "h-exe-001-v1",
        "event_type": "shadow_execution_observation",
        "exchange_timestamp_ms": probe.completion_timestamp_ms,
        **probe.to_dict(),
    }


def _replay_raw_session(
    raw_paths: list[Path], expected_observations: list[dict[str, Any]]
) -> tuple[bool, list[str]]:
    raw_records, errors = _read_gzip_records(raw_paths, label="RAW")
    analyzers: dict[str, ExecutionToxicityShadow] = {}
    replayed: list[dict[str, Any]] = []
    connection_id: int | None = None
    for index, event in enumerate(raw_records, start=1):
        try:
            current_connection = event.get("connection_id")
            if isinstance(current_connection, bool) or not isinstance(current_connection, int):
                raise ValueError("connection_id is missing")
            if current_connection <= 0:
                raise ValueError("connection_id is not positive")
            if connection_id is None:
                if current_connection != 1:
                    raise ValueError("first connection_id is not 1")
                connection_id = current_connection
            elif current_connection != connection_id:
                if current_connection != connection_id + 1:
                    raise ValueError("connection_id is not contiguous")
                for analyzer in analyzers.values():
                    analyzer.reset_connection()
                connection_id = current_connection
            product = event.get("product_id")
            if not isinstance(product, str) or not product.startswith("PF_"):
                raise ValueError("product_id is invalid")
            analyzer = analyzers.setdefault(product, ExecutionToxicityShadow(product))
            replayed.extend(_observation_record(item) for item in analyzer.process_event(event))
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            errors.append(f"RAW_REPLAY_INVALID:record-{index}:{exc}")
            break
    if replayed != expected_observations:
        errors.append("RAW_REPLAY_OBSERVATION_MISMATCH")
    return bool(raw_records) and not errors, errors


def evaluate_validation_journal(
    *,
    repo_root: Path,
    output_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    generated = (now or datetime.now(tz=UTC)).astimezone(UTC)
    root = Path(output_root)
    technical_health = aggregate_technical_health(
        repo_root=repo_root, output_root=root, now=generated
    )
    gate_root = root / "technical" / "ops" / "technical_gates"
    gate_paths = sorted(gate_root.glob("technical-gate-*.json"))
    if not gate_paths:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated.isoformat(),
            "status": "technical_gate_pending",
            "decision": "NO-GO",
            "technical_health": technical_health,
            "complete_validation_utc_days": 0,
            "completed_probes": 0,
            "safety": {
                "authorizes_orders": False,
                "authorizes_paper_or_live": False,
            },
        }

    gate_path = gate_paths[-1]
    gate = _load_json(gate_path)
    provenance = current_provenance(repo_root)
    ci_verified, ci_reasons, ci_path = _ci_receipt_valid(root, provenance, repo_root)
    required_gate = {
        "passed": True,
        "schema_version": "h-exe-001-v1",
        **provenance,
    }
    gate_errors = [
        f"TECHNICAL_GATE_MISMATCH:{key}"
        for key, expected in required_gate.items()
        if gate.get(key) != expected
    ]
    if int(gate.get("complete_utc_days", 0)) < 14:
        gate_errors.append("TECHNICAL_GATE_FEWER_THAN_14_DAYS")
    if int(gate.get("sequence_gaps", -1)) != 0:
        gate_errors.append("TECHNICAL_GATE_SEQUENCE_GAPS")

    phase_root = root / "validation"
    journal_rows, errors = read_session_journal(phase_root / "sessions.jsonl")
    errors.extend(gate_errors)
    observations: list[CompletedProbe] = []
    intervals_by_day: dict[date, list[tuple[int, int]]] = {}
    seen_sessions: set[str] = set()
    expected_code_hashes = {
        key: value for key, value in provenance.items() if key != "preregistration_sha256"
    }
    valid_sessions = 0
    replay_results: list[bool] = []

    for row in journal_rows:
        session_id = str(row.get("session_id", ""))
        if not session_id or session_id in seen_sessions:
            errors.append("DUPLICATE_OR_EMPTY_VALIDATION_SESSION")
            continue
        seen_sessions.add(session_id)
        if row.get("phase") != "validation":
            errors.append(f"VALIDATION_PHASE_MISMATCH:{session_id}")
            continue
        raw_summary_path = row.get("summary_path")
        if not isinstance(raw_summary_path, str):
            errors.append(f"VALIDATION_SUMMARY_PATH_MISSING:{session_id}")
            continue
        summary_path = Path(raw_summary_path)
        if not _inside(summary_path, phase_root) or not summary_path.is_file():
            errors.append(f"VALIDATION_SUMMARY_PATH_INVALID:{session_id}")
            continue
        if sha256_file(summary_path) != row.get("summary_sha256"):
            errors.append(f"VALIDATION_SUMMARY_HASH_MISMATCH:{session_id}")
            continue
        try:
            summary = _load_json(summary_path)
        except ValueError as exc:
            errors.append(f"VALIDATION_SUMMARY_INVALID:{session_id}:{exc}")
            continue
        if (
            summary.get("phase") != "validation"
            or summary.get("preregistration", {}).get("sha256")
            != provenance["preregistration_sha256"]
            or summary.get("code_hashes") != expected_code_hashes
            or summary.get("technical_gate") != gate
        ):
            errors.append(f"VALIDATION_SOURCE_HASH_MISMATCH:{session_id}")
            continue
        session = summary.get("session", {})
        if (
            session.get("valid") is not True
            or session.get("public_feeds_only") is not True
            or session.get("credentials_used") is not False
            or int(session.get("orders_sent", -1)) != 0
        ):
            errors.append(f"VALIDATION_SESSION_INVALID:{session_id}")
            continue
        collector = summary.get("collector", {})
        raw_files, raw_errors = _verified_manifest_files(
            collector.get("raw"), phase_root=phase_root, label="RAW"
        )
        observation_files, observation_errors = _verified_manifest_files(
            collector.get("observations"),
            phase_root=phase_root,
            label="OBSERVATION",
        )
        errors.extend(f"{session_id}:{error}" for error in raw_errors)
        errors.extend(f"{session_id}:{error}" for error in observation_errors)
        if raw_errors or observation_errors:
            continue
        session_probes, observation_records, probe_errors = _read_observations(observation_files)
        errors.extend(f"{session_id}:{error}" for error in probe_errors)
        expected_rows = int(collector.get("observations", {}).get("rows_written", -1))
        if probe_errors or expected_rows != len(session_probes):
            errors.append(f"VALIDATION_OBSERVATION_COUNT_MISMATCH:{session_id}")
            continue
        if not raw_files and int(collector.get("raw", {}).get("rows_written", 0)) > 0:
            errors.append(f"VALIDATION_RAW_MANIFEST_EMPTY:{session_id}")
            continue
        raw_records, raw_read_errors = _read_gzip_records(raw_files, label="RAW")
        expected_raw_rows = int(collector.get("raw", {}).get("rows_written", -1))
        if raw_read_errors or expected_raw_rows != len(raw_records):
            errors.extend(f"{session_id}:{error}" for error in raw_read_errors)
            errors.append(f"VALIDATION_RAW_COUNT_MISMATCH:{session_id}")
            continue
        replay_verified, replay_errors = _replay_raw_session(raw_files, observation_records)
        replay_results.append(replay_verified)
        errors.extend(f"{session_id}:{error}" for error in replay_errors)
        if replay_errors:
            continue
        windows = collector.get("connection_windows")
        if not isinstance(windows, list) or not windows:
            errors.append(f"VALIDATION_CONNECTION_WINDOWS_INVALID:{session_id}")
            continue
        parsed_windows: list[tuple[int, int]] = []
        for window in windows:
            if (
                not isinstance(window, list)
                or len(window) != 2
                or not isinstance(window[0], int)
                or not isinstance(window[1], int)
                or window[1] <= window[0]
            ):
                errors.append(f"VALIDATION_CONNECTION_WINDOW_INVALID:{session_id}")
                parsed_windows = []
                break
            parsed_windows.append((window[0], window[1]))
        if not parsed_windows:
            continue
        valid_sessions += 1
        observations.extend(session_probes)
        for start_ms, end_ms in parsed_windows:
            for day, day_start, day_end in _split_interval_by_day(start_ms, end_ms):
                intervals_by_day.setdefault(day, []).append((day_start, day_end))

    probe_ids = [probe.probe_id for probe in observations]
    if len(set(probe_ids)) != len(probe_ids):
        errors.append("DUPLICATE_VALIDATION_PROBE_ID")

    coverage_by_day: dict[str, float] = {}
    complete_days: list[str] = []
    for day, intervals in sorted(intervals_by_day.items()):
        coverage = _merged_coverage_ms(intervals) / DAY_MS
        coverage_by_day[day.isoformat()] = coverage
        day_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        if day_end <= generated and coverage >= COMPLETE_DAY_COVERAGE:
            complete_days.append(day.isoformat())

    errors = list(dict.fromkeys(errors))
    sessions_verified = bool(journal_rows) and not errors
    raw_replay_verified = (
        sessions_verified
        and len(replay_results) == valid_sessions
        and bool(replay_results)
        and all(replay_results)
    )
    evaluation = evaluate_validation_evidence(
        observations,
        complete_utc_days=len(complete_days),
        sessions_verified=sessions_verified,
        raw_replay_verified=raw_replay_verified,
        ci_verified=ci_verified,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat(),
        "status": evaluation["status"],
        "decision": evaluation["decision"],
        "technical_gate_path": str(gate_path.resolve()),
        "technical_gate_sha256": sha256_file(gate_path),
        "source_hashes": provenance,
        "session_counts": {
            "journal_rows": len(journal_rows),
            "valid": valid_sessions,
        },
        "completed_probes": len(observations),
        "complete_validation_utc_days": len(complete_days),
        "complete_day_list": complete_days,
        "coverage_by_day": coverage_by_day,
        "sessions_verified": sessions_verified,
        "raw_replay_verified": raw_replay_verified,
        "ci": {
            "verified": ci_verified,
            "reason_codes": ci_reasons,
            "receipt_path": str(ci_path.resolve()),
        },
        "reason_codes": errors,
        "evaluation": evaluation,
        "safety": {
            "network_used": False,
            "credentials_used": False,
            "orders_sent": 0,
            "authorizes_paper_or_live": False,
        },
    }
