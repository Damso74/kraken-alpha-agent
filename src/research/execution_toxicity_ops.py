"""Local operations healthcheck and technical-gate builder for H-EXE-001."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "h-exe-001-v1"
MIN_COMPLETE_DAYS = 14
COMPLETE_DAY_COVERAGE = 0.99
DAY_MS = 86_400_000

PREREGISTRATION_RELATIVE_PATH = Path("docs/EXECUTION_TOXICITY_PREREGISTRATION.md")
CODE_RELATIVE_PATHS = {
    "collector_sha256": Path("src/data/collectors/kraken_execution_l2.py"),
    "supervisor_sha256": Path("src/data/collectors/kraken_execution_supervisor.py"),
    "engine_sha256": Path("src/research/execution_toxicity.py"),
    "ops_sha256": Path("src/research/execution_toxicity_ops.py"),
    "runner_sha256": Path("scripts/run_execution_toxicity_shadow.py"),
    "ops_runner_sha256": Path("scripts/run_execution_toxicity_ops_once.py"),
    "validation_sha256": Path("src/research/execution_toxicity_validation.py"),
    "validation_runner_sha256": Path("scripts/evaluate_execution_toxicity_validation.py"),
    "ci_attestation_sha256": Path("src/research/ci_attestation.py"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_provenance(repo_root: Path) -> dict[str, str]:
    root = Path(repo_root)
    return {
        "preregistration_sha256": sha256_file(root / PREREGISTRATION_RELATIVE_PATH),
        **{
            label: sha256_file(root / relative_path)
            for label, relative_path in CODE_RELATIVE_PATHS.items()
        },
    }


def read_session_journal(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.is_file():
        return [], ["SESSION_JOURNAL_MISSING"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"INVALID_JOURNAL_JSON_LINE_{line_number}")
            continue
        if not isinstance(row, dict):
            errors.append(f"INVALID_JOURNAL_ROW_{line_number}")
            continue
        rows.append(row)
    return rows, errors


def _split_interval_by_day(start_ms: int, end_ms: int) -> list[tuple[date, int, int]]:
    if end_ms <= start_ms:
        return []
    out: list[tuple[date, int, int]] = []
    cursor = start_ms
    while cursor < end_ms:
        dt = datetime.fromtimestamp(cursor / 1000.0, tz=UTC)
        day = dt.date()
        next_day = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        boundary_ms = int(next_day.timestamp() * 1000)
        segment_end = min(end_ms, boundary_ms)
        day_start_ms = boundary_ms - DAY_MS
        out.append((day, cursor - day_start_ms, segment_end - day_start_ms))
        cursor = segment_end
    return out


def _merged_coverage_ms(intervals: Sequence[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    total = 0
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def _load_verified_summary(
    row: Mapping[str, Any], phase_root: Path
) -> tuple[dict[str, Any] | None, str | None]:
    raw_path = row.get("summary_path")
    if not isinstance(raw_path, str):
        return None, "SESSION_SUMMARY_PATH_MISSING"
    path = Path(raw_path).resolve()
    try:
        path.relative_to(phase_root.resolve())
    except ValueError:
        return None, "SESSION_SUMMARY_OUTSIDE_PHASE_ROOT"
    if not path.is_file():
        return None, "SESSION_SUMMARY_MISSING"
    expected_sha = row.get("summary_sha256")
    if not isinstance(expected_sha, str) or sha256_file(path) != expected_sha:
        return None, "SESSION_SUMMARY_HASH_MISMATCH"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "SESSION_SUMMARY_INVALID_JSON"
    if not isinstance(payload, dict):
        return None, "SESSION_SUMMARY_NOT_OBJECT"
    return payload, None


def aggregate_technical_health(
    *,
    repo_root: Path,
    output_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    now_utc = now.astimezone(UTC) if now is not None else datetime.now(tz=UTC)
    phase_root = Path(output_root) / "technical"
    journal_rows, reasons = read_session_journal(phase_root / "sessions.jsonl")
    provenance = current_provenance(Path(repo_root))
    seen_ids: set[str] = set()
    intervals_by_day: dict[date, list[tuple[int, int]]] = {}
    valid_sessions = 0
    invalid_sessions = 0
    hash_mismatches = 0
    sequence_gaps = 0
    connection_errors = 0
    discarded_pending = 0

    for row in journal_rows:
        session_id = str(row.get("session_id", ""))
        if not session_id or session_id in seen_ids:
            reasons.append("DUPLICATE_OR_EMPTY_SESSION_ID")
            continue
        seen_ids.add(session_id)
        summary, summary_error = _load_verified_summary(row, phase_root)
        if summary_error is not None:
            reasons.append(summary_error)
            continue
        assert summary is not None
        exact_hashes = all(row.get(key) == value for key, value in provenance.items())
        exact_hashes = (
            exact_hashes
            and summary.get("preregistration", {}).get("sha256")
            == provenance["preregistration_sha256"]
        )
        exact_hashes = exact_hashes and summary.get("code_hashes") == {
            key: value for key, value in provenance.items() if key != "preregistration_sha256"
        }
        if not exact_hashes:
            hash_mismatches += 1
            continue
        session = summary.get("session", {})
        invalid_reason = str(session.get("invalid_reason") or "")
        if "sequence gap" in invalid_reason.lower():
            sequence_gaps += 1
        if not bool(session.get("valid")):
            invalid_sessions += 1
            continue
        collector = summary.get("collector", {})
        raw_windows = collector.get("connection_windows")
        if not isinstance(raw_windows, list) or not raw_windows:
            reasons.append("SESSION_EXCHANGE_WINDOW_INVALID")
            continue
        connection_windows: list[tuple[int, int]] = []
        for raw_window in raw_windows:
            if (
                not isinstance(raw_window, list)
                or len(raw_window) != 2
                or not isinstance(raw_window[0], int)
                or not isinstance(raw_window[1], int)
                or raw_window[1] <= raw_window[0]
            ):
                reasons.append("SESSION_EXCHANGE_WINDOW_INVALID")
                connection_windows = []
                break
            connection_windows.append((raw_window[0], raw_window[1]))
        if not connection_windows:
            continue
        valid_sessions += 1
        connection_errors += int(collector.get("connection_error_count", 0))
        for counts in summary.get("engine_counts", {}).values():
            if isinstance(counts, Mapping):
                discarded_pending += int(counts.get("discarded_pending_on_reset", 0))
        for start_ms, end_ms in connection_windows:
            for day, day_start, day_end in _split_interval_by_day(start_ms, end_ms):
                intervals_by_day.setdefault(day, []).append((day_start, day_end))

    coverage_by_day: dict[str, float] = {}
    complete_days: list[str] = []
    for day, intervals in sorted(intervals_by_day.items()):
        coverage = _merged_coverage_ms(intervals) / DAY_MS
        coverage_by_day[day.isoformat()] = coverage
        day_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        if day_end <= now_utc and coverage >= COMPLETE_DAY_COVERAGE:
            complete_days.append(day.isoformat())

    if invalid_sessions:
        reasons.append("INVALID_SESSIONS_PRESENT")
    if hash_mismatches:
        reasons.append("SESSION_HASH_MISMATCHES_PRESENT")
    if sequence_gaps:
        reasons.append("UNRESOLVED_SEQUENCE_GAPS")
    if len(complete_days) < MIN_COMPLETE_DAYS:
        reasons.append("FEWER_THAN_14_COMPLETE_UTC_DAYS")
    reasons = list(dict.fromkeys(reasons))
    passed = not reasons
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_utc.isoformat(),
        "passed": passed,
        "reason_codes": reasons or ["TECHNICAL_GATE_PASSED"],
        "session_counts": {
            "journal_rows": len(journal_rows),
            "valid": valid_sessions,
            "invalid": invalid_sessions,
            "hash_mismatches": hash_mismatches,
        },
        "complete_utc_days": len(complete_days),
        "complete_day_list": complete_days,
        "coverage_threshold": COMPLETE_DAY_COVERAGE,
        "coverage_by_day": coverage_by_day,
        "sequence_gaps": sequence_gaps,
        "resolved_connection_errors": connection_errors,
        "discarded_pending_on_reconnect": discarded_pending,
        **provenance,
    }


def technical_gate_payload(health: Mapping[str, Any]) -> dict[str, Any]:
    if not bool(health.get("passed")):
        raise ValueError("technical health has not passed")
    keys = (
        "schema_version",
        "generated_at",
        "complete_utc_days",
        "complete_day_list",
        "coverage_threshold",
        "sequence_gaps",
        "preregistration_sha256",
        *CODE_RELATIVE_PATHS.keys(),
    )
    payload = {key: health[key] for key in keys}
    payload.update(
        {
            "passed": True,
            "human_review_required": True,
            "authorizes_orders": False,
            "authorizes_validation_collection_only": True,
        }
    )
    return payload


def health_digest_markdown(health: Mapping[str, Any], gate_path: Path | None) -> str:
    counts = health["session_counts"]
    lines = [
        "# H-EXE-001 — digest opérationnel technique",
        "",
        f"- Généré à : `{health['generated_at']}`",
        f"- Gate technique : `{health['passed']}`",
        f"- Jours UTC complets : `{health['complete_utc_days']}` / `{MIN_COMPLETE_DAYS}`",
        f"- Sessions valides : `{counts['valid']}`",
        f"- Sessions invalides : `{counts['invalid']}`",
        f"- Hashes incompatibles : `{counts['hash_mismatches']}`",
        f"- Gaps de séquence non résolus : `{health['sequence_gaps']}`",
        f"- Reconnexions résolues : `{health['resolved_connection_errors']}`",
        f"- Probes abandonnés aux reconnexions : `{health['discarded_pending_on_reconnect']}`",
        f"- Raisons : `{', '.join(health['reason_codes'])}`",
        f"- Gate émis : `{str(gate_path.resolve()) if gate_path else 'non'}`",
        "",
        "Aucun ordre, identifiant privé ou activation live n'est couvert par ce digest.",
        "",
    ]
    return "\n".join(lines)
