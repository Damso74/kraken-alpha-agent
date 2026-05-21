"""Persistent state store for paper daemon (Phase 19, file-based, no secrets)."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class DaemonState:
    asset: str = "BTC"
    timeframe: str = "1d"
    strategy: str = "regime_router"
    cash_usd: float = 1000.0
    last_processed_timestamp: int | None = None
    last_bar_index: int = -1
    equity: float = 1000.0
    iteration: int = 0
    mode: str = "observation"
    updated_at_utc: str = ""
    overlay: str = ""
    state_schema_version: int = 0
    migrated_from_legacy: bool = False


@dataclass
class PositionState:
    symbol: str = ""
    quantity: float = 0.0
    avg_entry: float = 0.0
    bars_held: int = 0


@dataclass
class StateBundle:
    state: DaemonState = field(default_factory=DaemonState)
    positions: dict[str, PositionState] = field(default_factory=dict)


def _state_path(state_dir: Path) -> Path:
    return state_dir / "state.json"


def _positions_path(state_dir: Path) -> Path:
    return state_dir / "positions.json"


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def atomic_write(path: Path, content: str) -> None:
    """Write via temp file + replace for crash safety."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def recover_from_partial_write(path: Path) -> bool:
    """Restore from .bak if main file missing or empty."""
    bak = _backup_path(path)
    if path.is_file() and path.stat().st_size > 0:
        return True
    if bak.is_file():
        shutil.copy2(bak, path)
        return True
    return False


def _daemon_state_fields() -> frozenset[str]:
    return frozenset(DaemonState.__dataclass_fields__)


def load_state(state_dir: Path | str) -> StateBundle:
    root = Path(state_dir)
    bundle = StateBundle()
    sp = _state_path(root)
    pp = _positions_path(root)
    recover_from_partial_write(sp)
    if sp.is_file():
        raw = json.loads(sp.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            from src.bot.observation_state_migration import (
                is_legacy_observation_state,
                migrate_observation_state,
            )

            target_id = root.name
            if is_legacy_observation_state(raw, target_id):
                raw = migrate_observation_state(raw, target_id)
            fields = _daemon_state_fields()
            bundle.state = DaemonState(**{k: v for k, v in raw.items() if k in fields})
    if pp.is_file():
        raw = json.loads(pp.read_text(encoding="utf-8"))
        bundle.positions = {
            k: PositionState(**v) for k, v in raw.items()
        }
    return bundle


def save_state(state_dir: Path | str, bundle: StateBundle) -> None:
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    bundle.state.updated_at_utc = datetime.now(UTC).isoformat()
    sp = _state_path(root)
    pp = _positions_path(root)
    if sp.is_file():
        shutil.copy2(sp, _backup_path(sp))
    if pp.is_file():
        shutil.copy2(pp, _backup_path(pp))
    atomic_write(sp, json.dumps(asdict(bundle.state), indent=2))
    atomic_write(
        pp,
        json.dumps({k: asdict(v) for k, v in bundle.positions.items()}, indent=2),
    )


def append_decision(state_dir: Path | str, record: dict[str, Any]) -> None:
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "decisions.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def append_trade(state_dir: Path | str, record: dict[str, Any]) -> None:
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "trades.csv"
    write_header = not path.is_file()
    cols = sorted(record.keys())
    with path.open("a", newline="", encoding="utf-8") as fh:
        if write_header:
            fh.write(",".join(cols) + "\n")
        fh.write(",".join(str(record.get(c, "")) for c in cols) + "\n")


def append_equity(state_dir: Path | str, timestamp: str | int, equity: float) -> None:
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "equity_curve.csv"
    write_header = not path.is_file()
    with path.open("a", encoding="utf-8") as fh:
        if write_header:
            fh.write("timestamp,equity\n")
        fh.write(f"{timestamp},{equity}\n")


def log_error(state_dir: Path | str, message: str) -> None:
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "errors.log"
    ts = datetime.now(UTC).isoformat()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{ts} {message}\n")
