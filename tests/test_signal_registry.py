"""Signal registry validation (Phase 12)."""

from __future__ import annotations

from pathlib import Path

from src.research.signal_registry import (
    DEFAULT_REGISTRY_PATH,
    load_signal_registry,
    signals_allowing_oos,
    validate_registry,
)


def test_registry_loads_and_blocks_oos() -> None:
    entries = load_signal_registry(DEFAULT_REGISTRY_PATH)
    assert entries
    assert signals_allowing_oos(entries) == []


def test_registry_validation_passes() -> None:
    errors = validate_registry(DEFAULT_REGISTRY_PATH)
    assert errors == []


def test_registry_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    errors = validate_registry(missing)
    assert any("missing" in e for e in errors)
