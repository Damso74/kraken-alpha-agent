"""Phase 30 — observation ops guard tests (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from src.bot.observation_ops_guards import (
    check_all_target_state_warnings,
    check_state_legacy_warning,
    should_skip_observation,
)


def test_should_skip_observation_when_flag_present(tmp_path: Path) -> None:
    stop = tmp_path / "STOP_OBSERVATION"
    assert should_skip_observation(stop) is False
    stop.write_text("manual stop\n", encoding="utf-8")
    assert should_skip_observation(stop) is True


def test_check_state_legacy_warning_detects_btc_regime_router() -> None:
    state = {
        "asset": "BTC",
        "timeframe": "1d",
        "strategy": "regime_router",
    }
    warnings = check_state_legacy_warning(state, target_label="trend_following_baseline")
    assert any("asset=" in w for w in warnings)
    assert any("regime_router" in w for w in warnings)
    assert any("timeframe=" in w for w in warnings)


def test_check_state_legacy_warning_clean_eth_state() -> None:
    state = {
        "asset": "ETH",
        "timeframe": "4h",
        "strategy": "trend_following+funding_basis",
    }
    assert check_state_legacy_warning(state) == []


def test_check_all_target_state_warnings_reads_dirs(tmp_path: Path) -> None:
    tf = tmp_path / "trend_following_baseline"
    ema = tmp_path / "ema_crossover_baseline"
    tf.mkdir()
    ema.mkdir()
    (tf / "state.json").write_text(
        json.dumps({"asset": "BTC", "timeframe": "1d", "strategy": "regime_router"}),
        encoding="utf-8",
    )
    (ema / "state.json").write_text(
        json.dumps(
            {
                "asset": "ETH",
                "timeframe": "4h",
                "strategy": "ema_crossover+funding_basis",
            }
        ),
        encoding="utf-8",
    )
    warnings = check_all_target_state_warnings([tf, ema])
    assert len(warnings) == 3
    assert all("trend_following_baseline" in w for w in warnings)
