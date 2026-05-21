"""Phase 30.4 — observation healthcheck tests (no network, no crontab)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.bot.observation_healthcheck import (
    check_stop_flag,
    find_latest_log,
    run_observation_healthcheck,
)


def _eth_state() -> dict:
    return {
        "asset": "ETH",
        "timeframe": "4h",
        "strategy": "trend_following+funding_basis",
        "updated_at_utc": datetime.now(UTC).isoformat(),
        "last_processed_timestamp": int(datetime.now(UTC).timestamp()),
    }


def _write_summary(path: Path, obs: Path, *, stale: int = 0, obs_only: bool = True) -> None:
    tf = obs / "trend_following_baseline"
    ema = obs / "ema_crossover_baseline"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "summary": {"observation_only": obs_only, "target_count": 2},
                "targets": [
                    {
                        "target": "trend_following_baseline",
                        "state_dir": str(tf),
                        "observation_only": True,
                        "decision_count": 2,
                        "stale_data_count": stale,
                    },
                    {
                        "target": "ema_crossover_baseline",
                        "state_dir": str(ema),
                        "observation_only": True,
                        "decision_count": 2,
                        "stale_data_count": 0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _seed_nominal(tmp_path: Path) -> tuple[Path, Path, Path]:
    obs = tmp_path / "obs"
    ops = obs / "ops_logs"
    ops.mkdir(parents=True)
    (ops / "run.log").write_text("ok\n", encoding="utf-8")
    (obs / "dashboard.html").write_text("<html></html>", encoding="utf-8")
    (obs / "alerts.json").write_text(
        json.dumps({"critical_count": 0, "warning_count": 0, "alerts": []}),
        encoding="utf-8",
    )
    for name in ("trend_following_baseline", "ema_crossover_baseline"):
        d = obs / name
        d.mkdir(parents=True)
        strat = (
            "trend_following+funding_basis"
            if "trend" in name
            else "ema_crossover+funding_basis"
        )
        (d / "state.json").write_text(
            json.dumps({**_eth_state(), "strategy": strat}),
            encoding="utf-8",
        )
    summary = tmp_path / "summary.json"
    _write_summary(summary, obs)
    return obs, summary, obs / "alerts.json"


def test_check_stop_flag_fail(tmp_path: Path) -> None:
    stop = tmp_path / "STOP_OBSERVATION"
    stop.write_text("halt", encoding="utf-8")
    chk = check_stop_flag(stop)
    assert chk["status"] == "fail"


def test_run_healthcheck_pass_nominal(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
        dashboard_path=obs / "dashboard.html",
        cron_active=False,
    )
    assert report["status"] == "pass"
    assert report["summary"]["fail_count"] == 0


def test_fail_on_stop_flag(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    (obs / "STOP_OBSERVATION").write_text("stop", encoding="utf-8")
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
    )
    assert report["status"] == "fail"


def test_fail_on_critical_alerts(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    alerts.write_text(
        json.dumps(
            {
                "critical_count": 1,
                "warning_count": 0,
                "alerts": [{"code": "kill_criteria", "severity": "critical", "message": "x"}],
            }
        ),
        encoding="utf-8",
    )
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
    )
    assert report["status"] == "fail"


def test_fail_missing_dashboard(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    (obs / "dashboard.html").unlink()
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
    )
    assert report["status"] == "fail"
    assert any(c["name"] == "dashboard_present" and c["status"] == "fail" for c in report["checks"])


def test_fail_wrong_asset_state(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    tf = obs / "trend_following_baseline" / "state.json"
    tf.write_text(
        json.dumps({"asset": "BTC", "timeframe": "4h", "strategy": "x"}),
        encoding="utf-8",
    )
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
    )
    assert report["status"] == "fail"


def test_warning_stale_data(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    _write_summary(summary, obs, stale=3)
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
    )
    assert report["status"] == "warning"
    assert any("stale_data" in c["name"] for c in report["checks"])


def test_fail_cron_active_no_log(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    for f in (obs / "ops_logs").glob("*.log"):
        f.unlink()
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
        cron_active=True,
    )
    assert report["status"] == "fail"


def test_fail_cron_log_older_than_6h(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    log = obs / "ops_logs" / "run.log"
    old = time.time() - (7 * 3600)
    import os

    os.utime(log, (old, old))
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
        cron_active=True,
        max_log_age_hours=6.0,
    )
    assert report["status"] == "fail"
    assert any(c["name"] == "ops_log_freshness" and c["status"] == "fail" for c in report["checks"])


def test_warning_log_4_to_6h(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    for f in (obs / "ops_logs").glob("*.log"):
        f.unlink()
    log = obs / "ops_logs" / "stale.log"
    log.write_text("x\n", encoding="utf-8")
    mid = time.time() - (5 * 3600)
    import os

    os.utime(log, (mid, mid))
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
        cron_active=False,
    )
    assert report["status"] == "warning"


def test_warning_decision_stuck_8h(tmp_path: Path) -> None:
    obs, summary, alerts = _seed_nominal(tmp_path)
    old_ts = (datetime.now(UTC) - timedelta(hours=10)).isoformat()
    state = _eth_state()
    state["updated_at_utc"] = old_ts
    (obs / "trend_following_baseline" / "state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    summary.write_text(
        json.dumps(
            {
                "summary": {"observation_only": True},
                "targets": [
                    {
                        "target": "trend_following_baseline",
                        "state_dir": str(obs / "trend_following_baseline"),
                        "decision_count": 1,
                        "stale_data_count": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = run_observation_healthcheck(
        observation_base=obs,
        summary_path=summary,
        alerts_path=alerts,
    )
    assert any(c["name"].startswith("decision_stuck") for c in report["checks"])


def test_find_latest_log(tmp_path: Path) -> None:
    ops = tmp_path / "ops_logs"
    ops.mkdir()
    (ops / "a.log").write_text("1", encoding="utf-8")
    time.sleep(0.01)
    (ops / "b.log").write_text("2", encoding="utf-8")
    latest = find_latest_log(ops)
    assert latest is not None
    assert latest.name == "b.log"
