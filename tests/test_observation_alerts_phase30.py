"""Phase 30.3 — observation alerts tests."""

from __future__ import annotations

import json
from pathlib import Path

from src.bot.observation_alerts import collect_observation_alerts, render_alerts_md


def _write_summary(path: Path, *, block_rate: float = 0.0, stale: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "target": "trend_following_baseline",
                        "block_rate_on_signals": block_rate,
                        "stale_data_count": stale,
                        "error_count": 0,
                        "errors_tail": [],
                        "equity": {
                            "overlay_return_pct_from_1k": 5.0,
                            "standalone_return_pct": 10.0,
                        },
                        "kill_criteria": {"should_kill": False, "reasons": []},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_stop_flag_is_critical(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    (obs / "STOP_OBSERVATION").write_text("test stop", encoding="utf-8")
    report = collect_observation_alerts(
        observation_base=obs,
        summary_path=tmp_path / "missing.json",
    )
    codes = [a.code for a in report.alerts]
    assert "stop_observation" in codes
    assert report.critical_count >= 1
    assert report.exit_code_recommended == 1


def test_stale_data_triggers_warning(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    summary = tmp_path / "summary.json"
    _write_summary(summary, stale=2)
    report = collect_observation_alerts(observation_base=obs, summary_path=summary)
    assert any(a.code == "stale_data" for a in report.alerts)


def test_high_block_rate_triggers_warning(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    summary = tmp_path / "summary.json"
    _write_summary(summary, block_rate=0.75)
    report = collect_observation_alerts(observation_base=obs, summary_path=summary)
    assert any(a.code == "high_block_rate" for a in report.alerts)


def test_legacy_state_warning(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    tf = obs / "trend_following_baseline"
    tf.mkdir(parents=True)
    (tf / "state.json").write_text(
        json.dumps({"asset": "BTC", "timeframe": "1d", "strategy": "regime_router"}),
        encoding="utf-8",
    )
    summary = tmp_path / "summary.json"
    _write_summary(summary)
    report = collect_observation_alerts(observation_base=obs, summary_path=summary)
    assert any(a.code == "state_legacy" for a in report.alerts)


def test_render_alerts_md_nonempty() -> None:
    report = collect_observation_alerts(
        observation_base=Path("nonexistent_obs_base_for_test"),
        summary_path=Path("nonexistent_summary.json"),
    )
    md = render_alerts_md(report)
    assert "# Observation alerts" in md
