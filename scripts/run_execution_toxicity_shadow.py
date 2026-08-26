"""Run bounded public-data shadow collection for H-EXE-001.

This command subscribes only to Kraken Futures public ``book`` and ``trade``
feeds.  It contains no credentials, private feed, execution adapter or order
command.  Every output remains local and is ignored by Git under
``data/collector_cache``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.collectors.kraken_execution_l2 import (  # noqa: E402
    ExecutionCollectorError,
    GlobalStorageBudget,
    KrakenExecutionL2Collector,
    RotatingGzipJsonlWriter,
)
from src.data.collectors.kraken_execution_supervisor import (  # noqa: E402
    SupervisionResult,
    run_supervised_shadow_once,
)
from src.research.execution_toxicity import (  # noqa: E402
    CompletedProbe,
    ExecutionToxicityShadow,
    summarize_shadow_observations,
)

PREREGISTRATION_PATH = Path("docs/EXECUTION_TOXICITY_PREREGISTRATION.md")
DEFAULT_OUTPUT_DIR = Path("data/collector_cache/kraken_execution_toxicity_hexe001")
DEFAULT_PRODUCTS = ("PF_XBTUSD", "PF_ETHUSD")
PROGRESS_INTERVAL_NS = 5_000_000_000
SOURCE_PATHS = {
    "collector_sha256": Path("src/data/collectors/kraken_execution_l2.py"),
    "supervisor_sha256": Path("src/data/collectors/kraken_execution_supervisor.py"),
    "engine_sha256": Path("src/research/execution_toxicity.py"),
    "ops_sha256": Path("src/research/execution_toxicity_ops.py"),
    "runner_sha256": Path("scripts/run_execution_toxicity_shadow.py"),
    "ops_runner_sha256": Path("scripts/run_execution_toxicity_ops_once.py"),
    "validation_sha256": Path("src/research/execution_toxicity_validation.py"),
    "validation_runner_sha256": Path("scripts/evaluate_execution_toxicity_validation.py"),
}


class ProgressHeartbeat:
    """Mutable operational heartbeat; scientific evidence remains append-only."""

    def __init__(
        self,
        path: Path,
        *,
        session_id: str,
        storage_budget: GlobalStorageBudget,
        interval_ns: int = PROGRESS_INTERVAL_NS,
    ) -> None:
        if interval_ns <= 0:
            raise ValueError("progress interval must be positive")
        self.path = Path(path)
        self.session_id = session_id
        self.storage_budget = storage_budget
        self.interval_ns = int(interval_ns)
        self.event_count = 0
        self.last_exchange_timestamp_ms: int | None = None
        self.last_received_wall_ns: int | None = None
        self.last_received_monotonic_ns: int | None = None
        self._last_written_monotonic_ns: int | None = None
        self._reserved_bytes = 0

    def observe(self, event: dict[str, Any]) -> None:
        monotonic_ns = int(event["received_monotonic_ns"])
        self.event_count += 1
        self.last_exchange_timestamp_ms = int(event["exchange_timestamp_ms"])
        self.last_received_wall_ns = int(event["received_wall_ns"])
        self.last_received_monotonic_ns = monotonic_ns
        if (
            self._last_written_monotonic_ns is None
            or monotonic_ns - self._last_written_monotonic_ns >= self.interval_ns
        ):
            self._write()

    def finalize(self) -> None:
        if self.event_count and (
            self._last_written_monotonic_ns != self.last_received_monotonic_ns
        ):
            self._write()

    def _payload(self) -> dict[str, Any]:
        wall_ns = self.last_received_wall_ns
        updated_at = (
            datetime.fromtimestamp(wall_ns / 1_000_000_000, tz=UTC).isoformat()
            if wall_ns is not None
            else None
        )
        return {
            "schema_version": "h-exe-001-progress-v1",
            "session_id": self.session_id,
            "updated_at": updated_at,
            "event_count": self.event_count,
            "last_exchange_timestamp_ms": self.last_exchange_timestamp_ms,
            "last_received_wall_ns": wall_ns,
            "last_received_monotonic_ns": self.last_received_monotonic_ns,
            "credentials_used": False,
            "orders_sent": 0,
        }

    def _write(self) -> None:
        content = json.dumps(self._payload(), indent=2, sort_keys=True)
        encoded_bytes = len(content.encode("utf-8"))
        self.storage_budget.reserve(max(0, encoded_bytes - self._reserved_bytes))
        self._reserved_bytes = max(self._reserved_bytes, encoded_bytes)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.path)
        self._last_written_monotonic_ns = self.last_received_monotonic_ns

    def manifest(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        return {
            "path": str(self.path.resolve()),
            "bytes": self.path.stat().st_size,
            "sha256": _sha256(self.path),
            **self._payload(),
        }


def _atomic_json(
    path: Path, payload: dict[str, Any], *, storage_budget: GlobalStorageBudget | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(payload, indent=2, sort_keys=True)
    if storage_budget is not None:
        storage_budget.reserve(len(content.encode("utf-8")))
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _atomic_text(
    path: Path, content: str, *, storage_budget: GlobalStorageBudget | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if storage_budget is not None:
        storage_budget.reserve(len(content.encode("utf-8")))
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _append_jsonl(
    path: Path, payload: dict[str, Any], *, storage_budget: GlobalStorageBudget | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
    if storage_budget is not None:
        storage_budget.reserve(len(line.encode("utf-8")))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_technical_gate(
    path: Path,
    preregistration_sha256: str,
    code_hashes: dict[str, str],
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionCollectorError(f"invalid technical gate {path}: {exc}") from exc
    required = {
        "passed": True,
        "schema_version": "h-exe-001-v1",
        "preregistration_sha256": preregistration_sha256,
        **code_hashes,
    }
    for key, expected in required.items():
        if payload.get(key) != expected:
            raise ExecutionCollectorError(
                f"technical gate mismatch: {key}={payload.get(key)!r}, expected {expected!r}"
            )
    if int(payload.get("complete_utc_days", 0)) < 14:
        raise ExecutionCollectorError("technical gate requires at least 14 complete UTC days")
    if int(payload.get("sequence_gaps", -1)) != 0:
        raise ExecutionCollectorError("technical gate requires sequence_gaps=0")
    return payload


def _observation_record(item: CompletedProbe) -> dict[str, Any]:
    return {
        "schema_version": "h-exe-001-v1",
        "event_type": "shadow_execution_observation",
        "exchange_timestamp_ms": item.completion_timestamp_ms,
        **item.to_dict(),
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = report["aggregate_summary"]
    gates = summary["gates"]
    return "\n".join(
        [
            "# H-EXE-001 — état de la collecte shadow",
            "",
            f"- Généré à : `{report['generated_at']}`",
            f"- Session valide : `{report['session']['valid']}`",
            f"- Produits : `{', '.join(report['products'])}`",
            f"- Observations terminées : `{summary['completed_probes']}`",
            f"- Statut : `{summary['status']}`",
            f"- Décision : `{summary['decision']}`",
            f"- Gates passés : `{gates['passed']}`",
            f"- Raisons : `{', '.join(gates['reason_codes'])}`",
            "",
            "Cette sortie est une observation fictive sur données publiques. Aucun ordre n'a été envoyé.",
            "",
        ]
    )


def run(args: argparse.Namespace) -> int:
    preregistration_sha256 = _sha256(PREREGISTRATION_PATH)
    code_hashes = {label: _sha256(path) for label, path in SOURCE_PATHS.items()}
    technical_gate: dict[str, Any] | None = None
    if args.phase == "validation":
        if args.technical_gate is None:
            raise ExecutionCollectorError("validation phase requires --technical-gate")
        technical_gate = _validate_technical_gate(
            Path(args.technical_gate), preregistration_sha256, code_hashes
        )
    started = datetime.now(tz=UTC)
    session_id = args.session_id or started.strftime("%Y%m%dT%H%M%S.%fZ")
    phase_root = Path(args.output_dir) / args.phase
    output_dir = phase_root / "sessions" / session_id
    if output_dir.exists():
        raise ExecutionCollectorError(f"immutable session already exists: {output_dir}")
    storage_cap_bytes = int(args.storage_cap_gib * 1024 * 1024 * 1024)
    storage_budget = GlobalStorageBudget(Path(args.output_dir), storage_cap_bytes)
    raw_writer = RotatingGzipJsonlWriter(
        output_dir / "raw",
        max_file_bytes=int(args.max_file_mib * 1024 * 1024),
        storage_cap_bytes=storage_cap_bytes,
        storage_budget=storage_budget,
    )
    observation_writer = RotatingGzipJsonlWriter(
        output_dir / "observations",
        max_file_bytes=int(args.max_file_mib * 1024 * 1024),
        storage_cap_bytes=storage_cap_bytes,
        storage_budget=storage_budget,
    )
    progress = ProgressHeartbeat(
        output_dir / "progress.json",
        session_id=session_id,
        storage_budget=storage_budget,
    )
    analyzers = {product: ExecutionToxicityShadow(product) for product in args.products}

    def on_market_event(event: dict[str, Any], _book: Any) -> None:
        progress.observe(event)
        completed = analyzers[event["product_id"]].process_event(event)
        for item in completed:
            observation_writer.append(_observation_record(item))

    collectors: list[KrakenExecutionL2Collector] = []

    def reset_analyzers() -> None:
        for analyzer in analyzers.values():
            analyzer.reset_connection()

    def collector_factory() -> KrakenExecutionL2Collector:
        collector = KrakenExecutionL2Collector(
            args.products,
            connection_id=len(collectors) + 1,
            writer=raw_writer,
            on_market_event=on_market_event,
            on_connection_reset=reset_analyzers,
        )
        collectors.append(collector)
        return collector

    started_at = started.isoformat()
    failure: str | None = None
    interrupted = False
    supervision: SupervisionResult | None = None
    try:
        supervision = run_supervised_shadow_once(
            collector_factory, duration_seconds=float(args.duration_seconds)
        )
    except KeyboardInterrupt:
        interrupted = True
        failure = "operator_interrupt"
    except ExecutionCollectorError as exc:
        failure = str(exc)
    finally:
        progress.finalize()
        raw_manifest = raw_writer.manifest()
        observation_manifest = observation_writer.manifest()

    completed = [item for analyzer in analyzers.values() for item in analyzer.completed]
    aggregate = summarize_shadow_observations(completed)
    per_product = {
        product: summarize_shadow_observations(analyzer.completed)
        for product, analyzer in analyzers.items()
    }
    if args.phase == "technical":
        aggregate = {
            **aggregate,
            "status": "technical_only",
            "decision": "NO-GO",
            "gates": {
                "passed": False,
                "reason_codes": ["TECHNICAL_PHASE_EXCLUDED_FROM_ECONOMIC_VERDICT"],
            },
        }
    report = {
        "schema_version": "h-exe-001-v1",
        "session_id": session_id,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "started_at": started_at,
        "products": list(args.products),
        "duration_seconds_requested": float(args.duration_seconds),
        "phase": args.phase,
        "preregistration": {
            "path": str(PREREGISTRATION_PATH.resolve()),
            "sha256": preregistration_sha256,
        },
        "code_hashes": code_hashes,
        "technical_gate": technical_gate,
        "session": {
            "valid": all(collector.valid for collector in collectors) and failure is None,
            "invalid_reason": next(
                (
                    collector.invalid_reason
                    for collector in collectors
                    if collector.invalid_reason is not None
                ),
                failure,
            ),
            "interrupted": interrupted,
            "public_feeds_only": True,
            "orders_sent": 0,
            "credentials_used": False,
        },
        "collector": {
            "raw": raw_manifest,
            "observations": observation_manifest,
            "progress": progress.manifest(),
            "connections_started": (
                supervision.connections_started if supervision is not None else len(collectors)
            ),
            "connection_error_count": (
                len(supervision.recoverable_connection_errors) if supervision is not None else 0
            ),
            "last_connection_error": (
                supervision.recoverable_connection_errors[-1]
                if supervision is not None and supervision.recoverable_connection_errors
                else None
            ),
            "messages_received": supervision.messages_received if supervision is not None else 0,
            "first_exchange_timestamp_ms": (
                supervision.first_exchange_timestamp_ms if supervision is not None else None
            ),
            "last_exchange_timestamp_ms": (
                supervision.last_exchange_timestamp_ms if supervision is not None else None
            ),
            "connection_windows": (
                [list(window) for window in supervision.connection_windows]
                if supervision is not None
                else []
            ),
        },
        "engine_counts": {
            product: {
                "book_events": analyzer.book_events,
                "trade_events": analyzer.trade_events,
                "pending_probes": analyzer.pending_count,
                "completed_probes": len(analyzer.completed),
                "connection_resets": analyzer.connection_resets,
                "discarded_pending_on_reset": analyzer.discarded_pending_on_reset,
            }
            for product, analyzer in analyzers.items()
        },
        "per_product_summary": per_product,
        "aggregate_summary": aggregate,
    }
    _atomic_json(output_dir / "summary.json", report, storage_budget=storage_budget)
    _atomic_text(output_dir / "summary.md", _markdown(report), storage_budget=storage_budget)
    _append_jsonl(
        phase_root / "sessions.jsonl",
        {
            "schema_version": "h-exe-001-session-journal-v1",
            "session_id": session_id,
            "phase": args.phase,
            "summary_path": str((output_dir / "summary.json").resolve()),
            "summary_sha256": _sha256(output_dir / "summary.json"),
            "generated_at": report["generated_at"],
            "valid": report["session"]["valid"],
            "first_exchange_timestamp_ms": report["collector"]["first_exchange_timestamp_ms"],
            "last_exchange_timestamp_ms": report["collector"]["last_exchange_timestamp_ms"],
            "preregistration_sha256": preregistration_sha256,
            **code_hashes,
        },
        storage_budget=storage_budget,
    )
    print(json.dumps(report["session"], sort_keys=True))
    print(f"summary={str((output_dir / 'summary.json').resolve())}")
    return 0 if report["session"]["valid"] else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H-EXE-001 public shadow collector")
    parser.add_argument("--duration-seconds", type=float, default=3600.0)
    parser.add_argument("--phase", choices=("technical", "validation"), default="technical")
    parser.add_argument("--technical-gate", type=Path)
    parser.add_argument("--session-id")
    parser.add_argument("--products", nargs="+", default=list(DEFAULT_PRODUCTS))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-file-mib", type=float, default=256.0)
    parser.add_argument("--storage-cap-gib", type=float, default=200.0)
    args = parser.parse_args()
    if args.duration_seconds <= 0:
        parser.error("--duration-seconds must be positive")
    if args.max_file_mib <= 0 or args.storage_cap_gib <= 0:
        parser.error("storage limits must be positive")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
