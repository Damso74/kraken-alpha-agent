"""Cache-only H-WOF-002 forward evaluator and evidence receipts.

This script never opens a network connection and never imports an execution
adapter.  It can establish a deterministic baseline, reproduce the same
journal in a later process, or run the repository CI scope and bind its receipt
to the frozen H-WOF sources.  Even a complete pass emits REVIEW_REQUIRED and
never authorizes paper/live or an order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.collect_world_order_flow_forward import (  # noqa: E402
    DEFAULT_ROOT,
    WEEK_OUTCOME_MANIFEST_SCHEMA,
    _current_source_hashes,
    _load_typed_manifest,
    _verify_week_outcome_file,
    healthcheck_forward,
)
from src.data.collectors._common import CollectorError  # noqa: E402
from src.research.world_order_flow import evaluate_forward_outcomes  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_SCHEMA = "hwof002-forward-evidence-v1"
CI_RECEIPT_SCHEMA = "hwof002-ci-receipt-v1"


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _evaluation_root(root: Path) -> Path:
    return Path(root) / "evaluations"


def _source_set_sha256(source_hashes: dict[str, str]) -> str:
    return _canonical_sha256(source_hashes)


def _ci_receipt_path(root: Path, source_hashes: dict[str, str]) -> Path:
    return _evaluation_root(root) / "ci_receipts" / f"ci-{_source_set_sha256(source_hashes)}.json"


def _load_verified_outcomes(root: Path) -> list[dict[str, Any]]:
    manifest = _load_typed_manifest(
        Path(root) / "week_outcome_manifest.jsonl",
        schema=WEEK_OUTCOME_MANIFEST_SCHEMA,
    )
    outcomes: list[dict[str, Any]] = []
    for record in manifest:
        week = date.fromisoformat(str(record["day"]))
        relative = Path(str(record["path"]))
        payload, digest = _verify_week_outcome_file(Path(root) / relative, expected_week_start=week)
        if (
            digest != record.get("sha256")
            or payload.get("source_hashes") != record.get("source_hashes")
            or payload.get("status") != record.get("status")
            or payload.get("row_count") != record.get("row_count")
        ):
            raise CollectorError(f"week outcome manifest mismatch for {week}")
        outcomes.append(payload)
    return outcomes


def _ci_receipt_valid(path: Path, *, source_hashes: dict[str, str]) -> tuple[bool, list[str]]:
    if not path.is_file():
        return False, ["CI_RECEIPT_MISSING"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, ["CI_RECEIPT_INVALID_JSON"]
    reasons: list[str] = []
    if payload.get("schema_version") != CI_RECEIPT_SCHEMA:
        reasons.append("CI_RECEIPT_SCHEMA_MISMATCH")
    if payload.get("source_hashes") != source_hashes:
        reasons.append("CI_RECEIPT_SOURCE_HASH_MISMATCH")
    if payload.get("ruff_scope") != "src tests scripts" or payload.get("ruff_passed") is not True:
        reasons.append("CI_RUFF_SCOPE_NOT_VERIFIED")
    if payload.get("pytest_passed") is not True or int(payload.get("pytest_collected", 0)) <= 0:
        reasons.append("CI_PYTEST_NOT_VERIFIED")
    if payload.get("safety_env") != {
        "ALLOW_LIVE_ORDERS": "false",
        "KRAKEN_CLI_TRANSPORT": "mock",
        "LIVE_TRADING": "false",
        "TRADING_MODE": "dry_run",
    }:
        reasons.append("CI_SAFETY_ENV_MISMATCH")
    return not reasons, reasons


def _scientific_payload(
    *,
    outcomes: list[dict[str, Any]],
    journal_sha256: str,
    source_hashes: dict[str, str],
    causal_journal_verified: bool,
) -> dict[str, Any]:
    evaluation = evaluate_forward_outcomes(
        outcomes,
        causal_journal_verified=causal_journal_verified,
        cache_reproduction_verified=False,
        ci_verified=False,
    )
    return {
        "journal_sha256": journal_sha256,
        "source_hashes": source_hashes,
        "metrics": {
            key: value
            for key, value in evaluation.items()
            if key not in {"status", "decision", "gates", "safety"}
        },
        "scientific_gates": {
            key: value
            for key, value in evaluation["gates"].items()
            if key not in {"cache_only_reproduction_exact", "ci_scope_verified"}
        },
    }


def evaluate_and_write(
    *, root: Path, mode: str, today: date | None = None
) -> tuple[dict[str, Any], Path]:
    if mode not in {"baseline", "verify-cache"}:
        raise ValueError(f"unsupported evaluation mode: {mode}")
    effective_today = today or datetime.now(tz=UTC).date()
    health = healthcheck_forward(root=root, today=effective_today)
    outcomes = _load_verified_outcomes(root)
    source_hashes = _current_source_hashes()
    scientific = _scientific_payload(
        outcomes=outcomes,
        journal_sha256=str(health["journal_sha256"]),
        source_hashes=source_hashes,
        causal_journal_verified=bool(health["healthy"]),
    )
    scientific_sha = _canonical_sha256(scientific)
    baseline_path = (
        _evaluation_root(root)
        / "baselines"
        / (f"baseline-{health['journal_sha256']}-{_source_set_sha256(source_hashes)}.json")
    )
    reproduction_verified = False
    reproduction_reasons: list[str] = []
    if mode == "baseline":
        if not baseline_path.is_file():
            _atomic_json(
                baseline_path,
                {
                    "schema_version": EVALUATION_SCHEMA,
                    "created_at": datetime.now(tz=UTC).isoformat(),
                    "scientific_sha256": scientific_sha,
                    "scientific": scientific,
                },
            )
        else:
            reproduction_reasons.append("SEPARATE_VERIFY_CACHE_INVOCATION_REQUIRED")
    else:
        if not baseline_path.is_file():
            reproduction_reasons.append("BASELINE_MISSING")
        else:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            if baseline.get("scientific_sha256") != scientific_sha:
                reproduction_reasons.append("CACHE_REPRODUCTION_MISMATCH")
            elif baseline.get("scientific") != scientific:
                reproduction_reasons.append("CACHE_REPRODUCTION_PAYLOAD_MISMATCH")
            else:
                reproduction_verified = True
                receipt = (
                    _evaluation_root(root)
                    / "reproduction_receipts"
                    / f"reproduction-{health['journal_sha256']}-{scientific_sha}.json"
                )
                if not receipt.is_file():
                    _atomic_json(
                        receipt,
                        {
                            "schema_version": EVALUATION_SCHEMA,
                            "verified_at": datetime.now(tz=UTC).isoformat(),
                            "journal_sha256": health["journal_sha256"],
                            "scientific_sha256": scientific_sha,
                            "exact": True,
                        },
                    )

    ci_path = _ci_receipt_path(root, source_hashes)
    ci_verified, ci_reasons = _ci_receipt_valid(ci_path, source_hashes=source_hashes)
    evaluation = evaluate_forward_outcomes(
        outcomes,
        causal_journal_verified=bool(health["healthy"]),
        cache_reproduction_verified=reproduction_verified,
        ci_verified=ci_verified,
    )
    generated = datetime.now(tz=UTC)
    payload = {
        "schema_version": EVALUATION_SCHEMA,
        "generated_at": generated.isoformat(),
        "mode": mode,
        "journal_health": health,
        "source_hashes": source_hashes,
        "scientific_sha256": scientific_sha,
        "reproduction": {
            "verified": reproduction_verified,
            "reason_codes": reproduction_reasons,
            "baseline_path": str(baseline_path.resolve()),
        },
        "ci": {
            "verified": ci_verified,
            "reason_codes": ci_reasons,
            "receipt_path": str(ci_path.resolve()),
        },
        "evaluation": evaluation,
        "safety": {
            "network_used": False,
            "credentials_used": False,
            "orders_sent": 0,
            "authorizes_paper_or_live": False,
        },
    }
    stamp = generated.strftime("%Y%m%dT%H%M%S.%fZ")
    digest_path = _evaluation_root(root) / "digests" / f"digest-{stamp}.json"
    _atomic_json(digest_path, payload)
    _atomic_json(_evaluation_root(root) / "latest.json", payload)
    return payload, digest_path


def _run_ci_attestation(*, root: Path) -> Path:
    source_hashes = _current_source_hashes()
    environment = os.environ.copy()
    safety_env = {
        "ALLOW_LIVE_ORDERS": "false",
        "KRAKEN_CLI_TRANSPORT": "mock",
        "LIVE_TRADING": "false",
        "TRADING_MODE": "dry_run",
    }
    environment.update(safety_env)
    commands = [
        [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"],
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    outputs: list[str] = []
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        outputs.append(completed.stdout + completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(
                f"CI attestation command failed ({completed.returncode}): "
                f"{' '.join(command)}\n{outputs[-1][-2000:]}"
            )
    collected = sum(
        int(match.group(1)) for match in re.finditer(r":\s+(\d+)\s*$", outputs[1], re.MULTILINE)
    )
    if collected <= 0:
        raise RuntimeError("could not establish pytest collected count")
    receipt = {
        "schema_version": CI_RECEIPT_SCHEMA,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "source_hashes": source_hashes,
        "source_set_sha256": _source_set_sha256(source_hashes),
        "ruff_scope": "src tests scripts",
        "ruff_passed": True,
        "pytest_collected": collected,
        "pytest_passed": True,
        "safety_env": safety_env,
    }
    path = _ci_receipt_path(root, source_hashes)
    _atomic_json(path, receipt)
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("baseline", "verify-cache", "attest-ci"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--as-of-date", type=date.fromisoformat)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "attest-ci":
            path = _run_ci_attestation(root=args.root)
            print(json.dumps({"ci_receipt": str(path.resolve())}, indent=2))
            return 0
        payload, digest = evaluate_and_write(
            root=args.root,
            mode=args.command,
            today=args.as_of_date,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        print(f"digest={digest.resolve()}")
        return 0 if payload["journal_health"]["healthy"] else 2
    except (CollectorError, OSError, RuntimeError, ValueError) as exc:
        print(f"H-WOF-002 evaluation blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
