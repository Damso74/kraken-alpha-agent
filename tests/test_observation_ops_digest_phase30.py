"""Phase 30.4 — observation ops digest tests (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from src.bot.observation_ops_digest import build_ops_digest, resolve_next_action


def test_next_action_fix_required_on_critical() -> None:
    action = resolve_next_action(
        alerts={"critical_count": 2, "alerts": []},
        health={"status": "pass"},
        stop_active=False,
        log_age_hours=1.0,
    )
    assert action == "fix_required"


def test_next_action_stop_observation() -> None:
    action = resolve_next_action(
        alerts={"critical_count": 0, "alerts": []},
        health={"status": "pass"},
        stop_active=True,
        log_age_hours=1.0,
    )
    assert action == "stop_observation"


def test_next_action_check_vps_cron_old_log() -> None:
    action = resolve_next_action(
        alerts={"critical_count": 0, "alerts": []},
        health={"status": "warning", "checks": []},
        stop_active=False,
        log_age_hours=8.0,
    )
    assert action == "check_vps_cron"


def test_next_action_continue_on_no_new_candle_info() -> None:
    action = resolve_next_action(
        alerts={
            "critical_count": 0,
            "alerts": [
                {
                    "code": "no_new_candle",
                    "severity": "info",
                    "message": "await bar",
                }
            ],
        },
        health={"status": "pass"},
        stop_active=False,
        log_age_hours=1.0,
    )
    assert action == "continue_observation"


def test_next_action_fix_required_stale_summary() -> None:
    action = resolve_next_action(
        alerts={"critical_count": 0, "alerts": []},
        health={"status": "pass"},
        summary={"targets": [{"stale_data_count": 1}]},
        stop_active=False,
        log_age_hours=1.0,
    )
    assert action == "fix_required"


def test_build_ops_digest_writes_structure(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    (obs / "dashboard.html").write_text("<html/>", encoding="utf-8")
    (obs / "alerts.json").write_text(
        json.dumps({"critical_count": 0, "warning_count": 0, "alerts": []}),
        encoding="utf-8",
    )
    (obs / "healthcheck.json").write_text(
        json.dumps({"status": "pass", "checks": []}),
        encoding="utf-8",
    )
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "target": "trend_following_baseline",
                        "decision_count": 1,
                        "trade_count": 10,
                        "stale_data_count": 0,
                        "block_rate_on_signals": 0.0,
                        "equity": {"overlay_return_pct_from_1k": 5.0},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    digest = build_ops_digest(
        observation_base=obs,
        summary_path=summary,
        alerts_path=obs / "alerts.json",
        health_path=obs / "healthcheck.json",
    )
    assert digest["next_action"] == "continue_observation"
    assert len(digest["targets"]) == 1
    assert "generated_at_utc" in digest
