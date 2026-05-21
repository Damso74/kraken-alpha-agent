"""Phase 30 — observation ops guard tests (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from src.bot.daemon_loop import is_duplicate_candle
from src.bot.observation_alerts import collect_observation_alerts
from src.bot.observation_ops_guards import (
    check_all_target_state_warnings,
    check_state_legacy_warning,
    should_skip_observation,
)
from src.bot.overlay_observation_engine import ObservationConfig, run_observation_once


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


def test_stop_observation_skips_daemon_via_engine(tmp_path: Path) -> None:
    base = tmp_path / "obs"
    state_dir = base / "trend_following_baseline"
    state_dir.mkdir(parents=True)
    (base / "STOP_OBSERVATION").write_text("halt", encoding="utf-8")
    cfg = ObservationConfig(state_dir=state_dir, cache_root=tmp_path / "cache")
    result = run_observation_once(cfg)
    assert result["status"] == "stopped"
    assert result["reason"] == "STOP_OBSERVATION flag"


def test_duplicate_candle_idempotence_mock() -> None:
    assert is_duplicate_candle(1779264000, 1779264000) is True
    assert is_duplicate_candle(1779264000, 1779278400) is False


def test_stale_data_triggers_alert_via_summary(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "target": "trend_following_baseline",
                        "block_rate_on_signals": 0.0,
                        "stale_data_count": 3,
                        "error_count": 0,
                        "errors_tail": [],
                        "equity": {},
                        "kill_criteria": {"should_kill": False, "reasons": []},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = collect_observation_alerts(observation_base=obs, summary_path=summary)
    assert any(a.code == "stale_data" for a in report.alerts)
