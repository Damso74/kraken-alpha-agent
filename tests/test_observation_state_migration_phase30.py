"""Phase 30.1 — observation state migration tests."""

from __future__ import annotations

import json
from pathlib import Path

from src.bot.observation_state_migration import (
    CURRENT_SCHEMA_VERSION,
    is_legacy_observation_state,
    migrate_observation_state,
)
from src.bot.state_store import DaemonState, StateBundle, append_decision, load_state, save_state


def test_migrate_legacy_btc_regime_router_to_eth_4h() -> None:
    legacy = {
        "asset": "BTC",
        "timeframe": "1d",
        "strategy": "regime_router",
        "cash_usd": 1112.08,
        "equity": 1112.08,
        "iteration": 1,
    }
    migrated = migrate_observation_state(legacy, "trend_following_baseline")
    assert migrated["asset"] == "ETH"
    assert migrated["timeframe"] == "4h"
    assert migrated["strategy"] == "trend_following+funding_basis"
    assert migrated["overlay"] == "funding_basis"
    assert migrated["state_schema_version"] == CURRENT_SCHEMA_VERSION
    assert migrated["migrated_from_legacy"] is True
    assert migrated["cash_usd"] == 1112.08
    assert migrated["equity"] == 1112.08


def test_migrate_ema_crossover_baseline() -> None:
    legacy = {
        "asset": "BTC",
        "timeframe": "1d",
        "strategy": "regime_router",
        "equity": 965.88,
    }
    migrated = migrate_observation_state(legacy, "ema_crossover_baseline")
    assert migrated["strategy"] == "ema_crossover+funding_basis"
    assert migrated["migrated_from_legacy"] is True


def test_clean_state_unchanged_except_schema_version() -> None:
    clean = {
        "asset": "ETH",
        "timeframe": "4h",
        "strategy": "trend_following+funding_basis",
        "overlay": "funding_basis",
        "cash_usd": 1000.0,
        "equity": 1000.0,
        "state_schema_version": CURRENT_SCHEMA_VERSION,
        "migrated_from_legacy": False,
    }
    migrated = migrate_observation_state(dict(clean), "trend_following_baseline")
    assert migrated == clean
    assert not is_legacy_observation_state(clean, "trend_following_baseline")


def test_decisions_history_preserved_on_disk(tmp_path: Path) -> None:
    state_dir = tmp_path / "trend_following_baseline"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "asset": "BTC",
                "timeframe": "1d",
                "strategy": "regime_router",
                "equity": 1000.0,
            }
        ),
        encoding="utf-8",
    )
    append_decision(state_dir, {"timestamp": 1, "overlay_decision": "allow"})
    append_decision(state_dir, {"timestamp": 2, "overlay_decision": "block"})

    bundle = load_state(state_dir)
    assert bundle.state.asset == "ETH"
    assert bundle.state.strategy == "trend_following+funding_basis"

    decisions = (state_dir / "decisions.jsonl").read_text(encoding="utf-8")
    assert decisions.count("\n") == 2
    assert "allow" in decisions
    assert "block" in decisions


def test_load_state_migrates_in_memory_without_touching_file(tmp_path: Path) -> None:
    state_dir = tmp_path / "ema_crossover_baseline"
    state_dir.mkdir()
    raw = {"asset": "BTC", "timeframe": "1d", "strategy": "regime_router"}
    (state_dir / "state.json").write_text(json.dumps(raw), encoding="utf-8")

    bundle = load_state(state_dir)
    assert bundle.state.asset == "ETH"
    on_disk = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert on_disk["asset"] == "BTC"

    save_state(state_dir, bundle)
    persisted = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    assert persisted["asset"] == "ETH"
    assert persisted["migrated_from_legacy"] is True
