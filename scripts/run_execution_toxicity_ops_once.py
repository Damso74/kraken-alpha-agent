"""One bounded H-EXE-001 technical collection + immutable local health digest."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_execution_toxicity_shadow import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PRODUCTS,
)
from scripts.run_execution_toxicity_shadow import (  # noqa: E402
    run as run_shadow,
)
from src.data.collectors.kraken_execution_l2 import (  # noqa: E402
    ExecutionCollectorError,
    GlobalStorageBudget,
)
from src.research.execution_toxicity_ops import (  # noqa: E402
    aggregate_technical_health,
    health_digest_markdown,
    technical_gate_payload,
)


def _atomic_json(
    path: Path, payload: dict[str, Any], *, storage_budget: GlobalStorageBudget
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(payload, indent=2, sort_keys=True)
    storage_budget.reserve(len(content.encode("utf-8")))
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _atomic_text(path: Path, content: str, *, storage_budget: GlobalStorageBudget) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    storage_budget.reserve(len(content.encode("utf-8")))
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _acquire_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ExecutionCollectorError(f"ops lock already exists: {path}") from exc
    os.write(descriptor, f"pid={os.getpid()}\n".encode())
    os.fsync(descriptor)
    return descriptor


def run(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    output_root = Path(args.output_dir)
    lock_path = output_root / ".ops-once.lock"
    lock_descriptor = _acquire_lock(lock_path)
    collection_exit = 0
    try:
        if not args.health_only:
            collection_exit = run_shadow(
                SimpleNamespace(
                    duration_seconds=args.duration_seconds,
                    phase="technical",
                    technical_gate=None,
                    session_id=None,
                    products=args.products,
                    output_dir=output_root,
                    max_file_mib=args.max_file_mib,
                    storage_cap_gib=args.storage_cap_gib,
                )
            )
        generated = datetime.now(tz=UTC)
        health = aggregate_technical_health(
            repo_root=repo_root,
            output_root=output_root,
            now=generated,
        )
        stamp = generated.strftime("%Y%m%dT%H%M%S.%fZ")
        ops_root = output_root / "technical" / "ops"
        storage_budget = GlobalStorageBudget(
            output_root, int(args.storage_cap_gib * 1024 * 1024 * 1024)
        )
        gate_path: Path | None = None
        if health["passed"]:
            gate_path = ops_root / "technical_gates" / f"technical-gate-{stamp}.json"
            _atomic_json(
                gate_path, technical_gate_payload(health), storage_budget=storage_budget
            )
        digest_json = ops_root / "digests" / f"digest-{stamp}.json"
        digest_md = ops_root / "digests" / f"digest-{stamp}.md"
        _atomic_json(digest_json, health, storage_budget=storage_budget)
        _atomic_text(
            digest_md,
            health_digest_markdown(health, gate_path),
            storage_budget=storage_budget,
        )
        print(f"digest={digest_json.resolve()}")
        print(f"technical_gate={gate_path.resolve() if gate_path else 'not-issued'}")
        return collection_exit
    finally:
        os.close(lock_descriptor)
        lock_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="H-EXE-001 bounded local ops run")
    parser.add_argument("--duration-seconds", type=float, default=300.0)
    parser.add_argument("--products", nargs="+", default=list(DEFAULT_PRODUCTS))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-file-mib", type=float, default=256.0)
    parser.add_argument("--storage-cap-gib", type=float, default=200.0)
    parser.add_argument("--health-only", action="store_true")
    args = parser.parse_args()
    if args.duration_seconds <= 0:
        parser.error("--duration-seconds must be positive")
    return args


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
