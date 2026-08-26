"""Write a cache-only, non-authorizing H-EXE-001 validation digest."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_execution_toxicity_shadow import DEFAULT_OUTPUT_DIR  # noqa: E402
from src.research.execution_toxicity_ops import current_provenance  # noqa: E402
from src.research.execution_toxicity_validation import (  # noqa: E402
    CI_RECEIPT_SCHEMA,
    ci_receipt_path,
    evaluate_validation_journal,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def evaluate_and_write(*, output_root: Path) -> tuple[dict, Path]:
    report = evaluate_validation_journal(
        repo_root=REPO_ROOT,
        output_root=output_root,
    )
    generated = datetime.fromisoformat(str(report["generated_at"])).astimezone(UTC)
    stamp = generated.strftime("%Y%m%dT%H%M%S.%fZ")
    ops_root = Path(output_root) / "validation" / "ops" / "evaluations"
    digest = ops_root / "digests" / f"digest-{stamp}.json"
    _atomic_json(digest, report)
    _atomic_json(ops_root / "latest.json", report)
    return report, digest


def run_ci_attestation(*, output_root: Path) -> Path:
    source_hashes = current_provenance(REPO_ROOT)
    safety_env = {
        "ALLOW_LIVE_ORDERS": "false",
        "KRAKEN_CLI_TRANSPORT": "mock",
        "LIVE_TRADING": "false",
        "TRADING_MODE": "dry_run",
    }
    environment = os.environ.copy()
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
    path = ci_receipt_path(output_root, source_hashes)
    _atomic_json(
        path,
        {
            "schema_version": CI_RECEIPT_SCHEMA,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "source_hashes": source_hashes,
            "ruff_scope": "src tests scripts",
            "ruff_passed": True,
            "pytest_collected": collected,
            "pytest_passed": True,
            "safety_env": safety_env,
        },
    )
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("evaluate", "attest-ci"), nargs="?", default="evaluate")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "attest-ci":
            path = run_ci_attestation(output_root=args.output_root)
            print(json.dumps({"ci_receipt": str(path.resolve())}, indent=2))
            return 0
        report, digest = evaluate_and_write(output_root=args.output_root)
        print(json.dumps(report, indent=2, sort_keys=True))
        print(f"digest={digest.resolve()}")
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"H-EXE-001 validation evaluation blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
