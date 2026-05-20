"""Tests for state store (Phase 19)."""

from __future__ import annotations

import json

from src.bot.state_store import (
    DaemonState,
    StateBundle,
    append_decision,
    append_equity,
    atomic_write,
    load_state,
    recover_from_partial_write,
    save_state,
)


def test_save_load_roundtrip(tmp_path) -> None:
    bundle = StateBundle(state=DaemonState(asset="BTC", equity=1050.0))
    save_state(tmp_path, bundle)
    loaded = load_state(tmp_path)
    assert loaded.state.asset == "BTC"
    assert loaded.state.equity == 1050.0


def test_atomic_write_and_recover(tmp_path) -> None:
    path = tmp_path / "state.json"
    atomic_write(path, json.dumps({"ok": True}))
    assert recover_from_partial_write(path)


def test_append_decision_and_equity(tmp_path) -> None:
    append_decision(tmp_path, {"action": "hold"})
    append_equity(tmp_path, 123, 1000.0)
    assert (tmp_path / "decisions.jsonl").is_file()
    assert (tmp_path / "equity_curve.csv").is_file()
