#!/usr/bin/env python3
"""Phase 30.1 — migrate legacy observation state.json metadata (dry-run or apply)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.observation_state_migration import (
    TARGET_METADATA,
    is_legacy_observation_state,
    migrate_observation_state,
)
from src.bot.overlay_observation_engine import PHASE28_TARGETS, default_state_dir
from src.bot.state_store import atomic_write

DEFAULT_BASE = REPO_ROOT / "reports" / "paper_observation_phase28"


def _target_dirs(state_base: Path) -> list[Path]:
    return [
        default_state_dir(state_base, strategy, variant)
        for strategy, variant, _ in PHASE28_TARGETS
    ]


def migrate_dir(state_dir: Path, *, apply: bool) -> dict[str, object]:
    path = state_dir / "state.json"
    if not path.is_file():
        return {"target": state_dir.name, "status": "missing", "changed": False}

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"target": state_dir.name, "status": "invalid", "changed": False}

    target_id = state_dir.name
    legacy = is_legacy_observation_state(raw, target_id)
    migrated = migrate_observation_state(raw, target_id)
    changed = migrated != raw

    if apply and changed:
        atomic_write(path, json.dumps(migrated, indent=2))

    return {
        "target": target_id,
        "status": "legacy" if legacy else "ok",
        "changed": changed,
        "before": {k: raw.get(k) for k in ("asset", "timeframe", "strategy", "overlay")},
        "after": {k: migrated.get(k) for k in ("asset", "timeframe", "strategy", "overlay")},
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 30.1 observation state migration")
    p.add_argument("--state-base", type=Path, default=DEFAULT_BASE)
    p.add_argument("--dry-run", action="store_true", default=False)
    p.add_argument("--apply", action="store_true", default=False)
    args = p.parse_args()

    apply = args.apply and not args.dry_run
    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply", file=sys.stderr)
        return 2

    results = [migrate_dir(d, apply=apply) for d in _target_dirs(args.state_base)]
    payload = {
        "mode": "apply" if apply else "dry-run",
        "targets_known": list(TARGET_METADATA.keys()),
        "results": results,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
