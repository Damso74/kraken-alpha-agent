"""Fast scheduled health digest for the local H-EXE/H-WOF shadow production."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/collector_cache/edge_forward_health"
MIN_DISK_FREE_BYTES = 250 * 1024 * 1024 * 1024


def _latest(root: Path, pattern: str) -> Path | None:
    if not root.is_dir():
        return None
    matches = [path for path in root.rglob(pattern) if path.is_file()]
    return max(matches, key=lambda path: path.stat().st_mtime_ns, default=None)


def _file_state(path: Path, now: datetime) -> dict[str, Any]:
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "age_minutes": (now - modified).total_seconds() / 60.0,
        "last_write_utc": modified.isoformat(),
    }


def build_health(
    *,
    repo_root: Path,
    now: datetime | None = None,
    disk_free_bytes: int | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    generated = (now or datetime.now(tz=UTC)).astimezone(UTC)
    reasons: list[str] = []
    sessions_root = (
        root
        / "data/collector_cache/kraken_execution_toxicity_hexe001/technical/sessions"
    )

    latest_raw = _latest(sessions_root, "*.jsonl.gz")
    raw_state: dict[str, Any] | None = None
    if latest_raw is None:
        reasons.append("H_EXE_RAW_MISSING")
    else:
        raw_state = _file_state(latest_raw, generated)
        raw_state["state"] = "receiving" if raw_state["bytes"] else "batch_buffering"

    latest_progress = _latest(sessions_root, "progress.json")
    progress_state: dict[str, Any] | None = None
    if latest_progress is None:
        reasons.append("H_EXE_PROGRESS_MISSING")
    else:
        progress_state = _file_state(latest_progress, generated)
        if progress_state["age_minutes"] > 2:
            reasons.append("H_EXE_PROGRESS_STALE_GT_2_MIN")
        try:
            progress = json.loads(latest_progress.read_text(encoding="utf-8"))
            if progress.get("schema_version") != "h-exe-001-progress-v1":
                reasons.append("H_EXE_PROGRESS_SCHEMA_INVALID")
            if int(progress.get("event_count", 0)) <= 0:
                reasons.append("H_EXE_PROGRESS_EVENT_COUNT_EMPTY")
            if progress.get("credentials_used") is not False or int(
                progress.get("orders_sent", -1)
            ) != 0:
                reasons.append("H_EXE_PROGRESS_SAFETY_INVARIANT_FAILED")
            progress_state.update(
                {
                    "event_count": int(progress.get("event_count", 0)),
                    "last_exchange_timestamp_ms": progress.get(
                        "last_exchange_timestamp_ms"
                    ),
                    "session_id": progress.get("session_id"),
                }
            )
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            reasons.append("H_EXE_PROGRESS_JSON_INVALID")

    snapshots: list[dict[str, Any]] = []
    for relative in ("snapshot_days", "kraken_universe_days"):
        snapshot_root = root / "data/collector_cache/world_order_flow_forward" / relative
        latest_snapshot = _latest(snapshot_root, "*.json")
        if latest_snapshot is None:
            reasons.append(f"WOF_SNAPSHOT_MISSING:{relative}")
            continue
        state = _file_state(latest_snapshot, generated)
        state["age_hours"] = state.pop("age_minutes") / 60.0
        if state["age_hours"] > 48:
            reasons.append(f"WOF_SNAPSHOT_STALE_GT_48_HOURS:{relative}")
        snapshots.append(state)

    free_bytes = (
        int(disk_free_bytes)
        if disk_free_bytes is not None
        else shutil.disk_usage(root).free
    )
    if free_bytes < MIN_DISK_FREE_BYTES:
        reasons.append("DISK_FREE_BELOW_250_GIB")

    return {
        "schema_version": "edge-forward-production-health-v1",
        "generated_at": generated.isoformat(),
        "healthy": not reasons,
        "reason_codes": reasons,
        "credentials_used": False,
        "orders_sent": 0,
        "tasks": {
            "h_exe": {"inspection": "scheduled_data_health"},
            "h_wof": {"inspection": "scheduled_data_health"},
        },
        "h_exe_raw": raw_state,
        "h_exe_progress": progress_state,
        "h_wof_snapshots": snapshots,
        "disk_free_gib": free_bytes / (1024**3),
    }


def write_health(payload: dict[str, Any], output_root: Path) -> Path:
    root = Path(output_root)
    digest_root = root / "digests"
    digest_root.mkdir(parents=True, exist_ok=True)
    generated = datetime.fromisoformat(str(payload["generated_at"])).astimezone(UTC)
    stamp = generated.strftime("%Y%m%dT%H%M%S.%fZ")
    content = json.dumps(payload, indent=2, sort_keys=True)
    digest_path = digest_root / f"digest-{stamp}.json"
    digest_temp = digest_path.with_suffix(".json.tmp")
    digest_temp.write_text(content, encoding="utf-8")
    digest_temp.replace(digest_path)
    latest_path = root / "latest.json"
    latest_temp = latest_path.with_suffix(".json.tmp")
    latest_temp.write_text(content, encoding="utf-8")
    latest_temp.replace(latest_path)
    return digest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_health(repo_root=args.repo_root)
    digest = write_health(payload, args.output_root)
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"digest={digest.resolve()}")
    return 0 if payload["healthy"] else 2


if __name__ == "__main__":
    sys.exit(main())
