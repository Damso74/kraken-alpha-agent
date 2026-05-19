"""Read-only signal registry for methodology sprints (Phase 12+)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REGISTRY_PATH = REPO_ROOT / "reports" / "signal_registry.json"


@dataclass(frozen=True)
class SignalRegistryEntry:
    signal_id: str
    hypothesis_id: str
    module: str
    status: str
    tradable: bool
    oos_allowed: bool
    notes: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SignalRegistryEntry:
        return cls(
            signal_id=str(raw["signal_id"]),
            hypothesis_id=str(raw.get("hypothesis_id", "")),
            module=str(raw.get("module", "")),
            status=str(raw.get("status", "research_only")),
            tradable=bool(raw.get("tradable", False)),
            oos_allowed=bool(raw.get("oos_allowed", False)),
            notes=str(raw.get("notes", "")),
        )


def load_signal_registry(path: Path | None = None) -> list[SignalRegistryEntry]:
    registry_path = path or DEFAULT_REGISTRY_PATH
    doc = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = doc.get("signals") or doc.get("entries") or []
    return [SignalRegistryEntry.from_mapping(e) for e in entries]


def lookup_signal(
    signal_id: str,
    entries: Sequence[SignalRegistryEntry] | None = None,
) -> SignalRegistryEntry | None:
    rows = entries if entries is not None else load_signal_registry()
    for row in rows:
        if row.signal_id == signal_id:
            return row
    return None


def signals_allowing_oos(
    entries: Sequence[SignalRegistryEntry] | None = None,
) -> list[SignalRegistryEntry]:
    rows = entries if entries is not None else load_signal_registry()
    return [r for r in rows if r.oos_allowed]


def validate_registry(path: Path | None = None) -> list[str]:
    """Return human-readable validation errors (empty = OK)."""
    errors: list[str] = []
    registry_path = path or DEFAULT_REGISTRY_PATH
    if not registry_path.is_file():
        return [f"missing registry: {registry_path}"]

    doc = json.loads(registry_path.read_text(encoding="utf-8"))
    version = doc.get("schema_version")
    if not version:
        errors.append("schema_version is required")

    seen: set[str] = set()
    for raw in doc.get("signals") or []:
        sid = str(raw.get("signal_id", ""))
        if not sid:
            errors.append("signal entry missing signal_id")
            continue
        if sid in seen:
            errors.append(f"duplicate signal_id: {sid}")
        seen.add(sid)
        if raw.get("tradable"):
            errors.append(f"{sid}: tradable must remain false in research registry")
        if raw.get("oos_allowed") and raw.get("status") in ("kill", "revoked"):
            errors.append(f"{sid}: oos_allowed conflicts with status {raw.get('status')}")

    return errors
