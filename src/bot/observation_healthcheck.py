"""Phase 30.4 — observation VPS healthcheck (stdlib-only, no live I/O)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from src.bot.observation_ops_guards import check_all_target_state_warnings
from src.bot.observation_state_migration import TARGET_METADATA
from src.bot.overlay_observation_engine import PHASE28_TARGETS, default_state_dir

DEFAULT_BASE = Path("reports/paper_observation_phase28")
DEFAULT_SUMMARY = Path("reports/phase29_observation_metrics/summary.json")
DEFAULT_ALERTS = DEFAULT_BASE / "alerts.json"
DEFAULT_DASHBOARD = DEFAULT_BASE / "dashboard.html"
DEFAULT_STOP = DEFAULT_BASE / "STOP_OBSERVATION"

EXPECTED_ASSET = "ETH"
EXPECTED_TIMEFRAME = "4h"
STUCK_DECISION_HOURS = 8.0
DASHBOARD_STALE_HOURS = 48.0


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON object from path; return empty dict if missing or invalid."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def file_age_seconds(path: Path) -> float | None:
    """Return age of file in seconds, or None if absent."""
    if not path.is_file():
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return max(0.0, datetime.now(UTC).timestamp() - mtime)


def find_latest_log(ops_logs: Path) -> Path | None:
    """Return newest *.log under ops_logs by mtime."""
    if not ops_logs.is_dir():
        return None
    logs = sorted(ops_logs.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def read_alerts(path: Path = DEFAULT_ALERTS) -> dict[str, Any]:
    return load_json(path)


def read_summary(path: Path = DEFAULT_SUMMARY) -> dict[str, Any]:
    return load_json(path)


def _check(
    name: str,
    status: str,
    message: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"name": name, "status": status, "message": message}
    if details:
        row["details"] = dict(details)
    return row


def check_stop_flag(stop_path: Path = DEFAULT_STOP) -> dict[str, Any]:
    if stop_path.is_file():
        reason = stop_path.read_text(encoding="utf-8").strip() or "manual stop"
        return _check(
            "stop_observation",
            "fail",
            f"STOP_OBSERVATION active: {reason}",
            details={"path": str(stop_path)},
        )
    return _check("stop_observation", "pass", "STOP_OBSERVATION absent")


def check_alert_severity(alerts: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    critical = int(alerts.get("critical_count") or 0)
    warning = int(alerts.get("warning_count") or 0)
    if critical > 0:
        checks.append(
            _check(
                "alerts_critical",
                "fail",
                f"critical_count={critical}",
                details={"critical_count": critical},
            )
        )
    else:
        checks.append(
            _check("alerts_critical", "pass", "no critical alerts")
        )
    if warning > 0:
        checks.append(
            _check(
                "alerts_warning",
                "warning",
                f"warning_count={warning}",
                details={"warning_count": warning},
            )
        )
    else:
        checks.append(
            _check("alerts_warning", "pass", "no warning alerts")
        )
    return checks


def check_target_state(
    observation_base: Path,
    summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    targets = summary.get("targets") or []
    if not targets:
        checks.append(
            _check(
                "targets_present",
                "fail",
                "no targets in summary.json",
            )
        )
        return checks

    checks.append(
        _check(
            "targets_present",
            "pass",
            f"target_count={len(targets)}",
            details={"target_count": len(targets)},
        )
    )

    obs_only = bool(summary.get("summary", {}).get("observation_only", True))
    if not obs_only:
        checks.append(
            _check(
                "observation_only",
                "fail",
                "summary.summary.observation_only is false",
            )
        )
    else:
        checks.append(
            _check("observation_only", "pass", "observation_only=true")
        )

    for target in targets:
        if not isinstance(target, Mapping):
            continue
        name = str(target.get("target") or "")
        state_dir = Path(str(target.get("state_dir") or observation_base / name))
        state_path = state_dir / "state.json"
        state = load_json(state_path)
        if not state:
            checks.append(
                _check(
                    f"state_{name}",
                    "fail",
                    f"missing or invalid state.json at {state_path}",
                )
            )
            continue

        asset = str(state.get("asset") or "").upper()
        timeframe = str(state.get("timeframe") or "")
        if asset != EXPECTED_ASSET:
            checks.append(
                _check(
                    f"state_asset_{name}",
                    "fail",
                    f"asset={asset!r} (expected {EXPECTED_ASSET})",
                    details={"target": name, "asset": asset},
                )
            )
        if timeframe != EXPECTED_TIMEFRAME:
            checks.append(
                _check(
                    f"state_timeframe_{name}",
                    "fail",
                    f"timeframe={timeframe!r} (expected {EXPECTED_TIMEFRAME})",
                    details={"target": name, "timeframe": timeframe},
                )
            )
        if asset == EXPECTED_ASSET and timeframe == EXPECTED_TIMEFRAME:
            checks.append(
                _check(
                    f"state_eth_4h_{name}",
                    "pass",
                    f"{name}: ETH 4h metadata OK",
                )
            )

        stale = int(target.get("stale_data_count") or 0)
        if stale > 0:
            checks.append(
                _check(
                    f"stale_data_{name}",
                    "warning",
                    f"stale_data_count={stale}",
                    details={"target": name, "stale_data_count": stale},
                )
            )

        dc = int(target.get("decision_count") or 0)
        updated_raw = str(state.get("updated_at_utc") or "")
        age_h: float | None = None
        if updated_raw:
            try:
                updated = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
                age_h = (datetime.now(UTC) - updated).total_seconds() / 3600.0
            except ValueError:
                pass
        if age_h is None:
            age_sec = file_age_seconds(state_path)
            if age_sec is not None:
                age_h = age_sec / 3600.0

        if dc <= 1 and age_h is not None and age_h >= STUCK_DECISION_HOURS:
            checks.append(
                _check(
                    f"decision_stuck_{name}",
                    "warning",
                    f"decision_count={dc} unchanged for {age_h:.1f}h",
                    details={"target": name, "decision_count": dc, "age_hours": age_h},
                )
            )

    state_dirs = [
        default_state_dir(observation_base, s, v) for s, v, _ in PHASE28_TARGETS
    ]
    legacy = check_all_target_state_warnings(state_dirs)
    if legacy:
        checks.append(
            _check(
                "state_legacy",
                "warning",
                f"{len(legacy)} legacy metadata warning(s)",
                details={"warnings": legacy},
            )
        )
    else:
        checks.append(
            _check("state_legacy", "pass", "no legacy state metadata warnings")
        )

    return checks


def check_last_processed_timestamp(
    observation_base: Path,
    *,
    max_no_candle_hours: float = 12.0,
) -> list[dict[str, Any]]:
    """Warn when last_processed_timestamp is very old (possible stale cache)."""
    checks: list[dict[str, Any]] = []
    now_ts = datetime.now(UTC).timestamp()
    for target_id in TARGET_METADATA:
        state_path = observation_base / target_id / "state.json"
        state = load_json(state_path)
        if not state:
            continue
        lpt = state.get("last_processed_timestamp")
        if lpt is None:
            continue
        try:
            age_h = (now_ts - float(lpt)) / 3600.0
        except (TypeError, ValueError):
            continue
        if age_h > max_no_candle_hours:
            checks.append(
                _check(
                    f"last_processed_{target_id}",
                    "warning",
                    f"last_processed_timestamp age {age_h:.1f}h",
                    details={"target": target_id, "age_hours": age_h},
                )
            )
    return checks


def check_cron_log_freshness(
    ops_logs: Path,
    *,
    cron_active: bool,
    max_fail_hours: float = 6.0,
    warn_hours: float = 4.0,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    latest = find_latest_log(ops_logs)
    if latest is None:
        if cron_active:
            checks.append(
                _check(
                    "ops_log_present",
                    "fail",
                    "no ops_logs/*.log while cron is active",
                )
            )
        else:
            checks.append(
                _check(
                    "ops_log_present",
                    "warning",
                    "no ops_logs/*.log yet (cron not active?)",
                )
            )
        return checks

    age_sec = file_age_seconds(latest)
    if age_sec is None:
        checks.append(
            _check("ops_log_freshness", "warning", "could not stat latest ops log")
        )
        return checks

    age_h = age_sec / 3600.0
    details = {"latest_log": latest.name, "age_hours": round(age_h, 2)}

    if cron_active and age_h > max_fail_hours:
        checks.append(
            _check(
                "ops_log_freshness",
                "fail",
                f"latest log {latest.name} is {age_h:.1f}h old (>{max_fail_hours}h)",
                details=details,
            )
        )
    elif age_h > warn_hours:
        checks.append(
            _check(
                "ops_log_freshness",
                "warning",
                f"latest log {latest.name} is {age_h:.1f}h old ({warn_hours}-{max_fail_hours}h)",
                details=details,
            )
        )
    else:
        checks.append(
            _check(
                "ops_log_freshness",
                "pass",
                f"latest log {latest.name} is {age_h:.1f}h old",
                details=details,
            )
        )
    return checks


def check_dashboard_exists(
    dashboard_path: Path = DEFAULT_DASHBOARD,
    *,
    stale_hours: float = DASHBOARD_STALE_HOURS,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if not dashboard_path.is_file():
        checks.append(
            _check(
                "dashboard_present",
                "fail",
                f"dashboard missing: {dashboard_path}",
            )
        )
        return checks

    checks.append(
        _check("dashboard_present", "pass", f"dashboard at {dashboard_path.name}")
    )
    age_sec = file_age_seconds(dashboard_path)
    if age_sec is not None:
        age_h = age_sec / 3600.0
        if age_h > stale_hours:
            checks.append(
                _check(
                    "dashboard_freshness",
                    "warning",
                    f"dashboard is {age_h:.1f}h old",
                    details={"age_hours": age_h},
                )
            )
        else:
            checks.append(
                _check(
                    "dashboard_freshness",
                    "pass",
                    f"dashboard is {age_h:.1f}h old",
                    details={"age_hours": age_h},
                )
            )
    return checks


def _no_new_candle_info_only(alerts: Mapping[str, Any]) -> bool:
    alert_rows = alerts.get("alerts") or []
    if not alert_rows:
        return False
    for row in alert_rows:
        if not isinstance(row, Mapping):
            return False
        if row.get("code") != "no_new_candle" or row.get("severity") != "info":
            return False
    return True


def run_observation_healthcheck(
    *,
    observation_base: Path = DEFAULT_BASE,
    summary_path: Path = DEFAULT_SUMMARY,
    alerts_path: Path = DEFAULT_ALERTS,
    dashboard_path: Path = DEFAULT_DASHBOARD,
    stop_path: Path | None = None,
    cron_active: bool = False,
    max_log_age_hours: float = 6.0,
) -> dict[str, Any]:
    """Run all health checks and return a JSON-serializable report."""
    stop = stop_path or observation_base / "STOP_OBSERVATION"
    if dashboard_path == DEFAULT_DASHBOARD:
        dashboard_path = observation_base / "dashboard.html"
    ops_logs = observation_base / "ops_logs"
    generated = datetime.now(UTC).isoformat()
    checks: list[dict[str, Any]] = []

    checks.append(check_stop_flag(stop))

    summary = read_summary(summary_path)
    if not summary:
        checks.append(
            _check(
                "summary_present",
                "fail",
                f"summary.json missing or empty: {summary_path}",
            )
        )
    else:
        checks.append(
            _check("summary_present", "pass", f"summary loaded from {summary_path.name}")
        )
        checks.extend(check_target_state(observation_base, summary))

    alerts = read_alerts(alerts_path)
    if not alerts:
        checks.append(
            _check(
                "alerts_present",
                "warning",
                f"alerts.json missing or empty: {alerts_path}",
            )
        )
    else:
        checks.append(
            _check("alerts_present", "pass", "alerts.json loaded")
        )
        checks.extend(check_alert_severity(alerts))

    checks.extend(
        check_cron_log_freshness(
            ops_logs,
            cron_active=cron_active,
            max_fail_hours=max_log_age_hours,
        )
    )
    checks.extend(check_dashboard_exists(dashboard_path))
    checks.extend(check_last_processed_timestamp(observation_base))

    if alerts and _no_new_candle_info_only(alerts):
        checks.append(
            _check(
                "no_new_candle_info",
                "pass",
                "only no_new_candle info alerts (awaiting next 4h bar)",
            )
        )

    fail_n = sum(1 for c in checks if c["status"] == "fail")
    warn_n = sum(1 for c in checks if c["status"] == "warning")
    pass_n = sum(1 for c in checks if c["status"] == "pass")

    if fail_n > 0:
        overall = "fail"
    elif warn_n > 0:
        overall = "warning"
    else:
        overall = "pass"

    critical = int(alerts.get("critical_count") or 0) if alerts else 0
    warning_alerts = int(alerts.get("warning_count") or 0) if alerts else 0

    return {
        "status": overall,
        "generated_at_utc": generated,
        "checks": checks,
        "summary": {
            "fail_count": fail_n,
            "warning_count": warn_n,
            "pass_count": pass_n,
            "check_total": len(checks),
            "alerts_critical_count": critical,
            "alerts_warning_count": warning_alerts,
            "cron_active": cron_active,
            "stop_observation_active": stop.is_file(),
            "observation_base": str(observation_base),
        },
    }


def render_healthcheck_md(report: Mapping[str, Any]) -> str:
    status = str(report.get("status") or "unknown").upper()
    summary = report.get("summary") or {}
    lines = [
        "# Observation healthcheck (Phase 30.4)",
        "",
        f"> Generated: {report.get('generated_at_utc', '')} UTC",
        "",
        f"**Overall status:** `{status}`",
        "",
        f"- Fail checks: **{summary.get('fail_count', 0)}**",
        f"- Warning checks: **{summary.get('warning_count', 0)}**",
        f"- Pass checks: **{summary.get('pass_count', 0)}**",
        f"- Alerts critical: **{summary.get('alerts_critical_count', 0)}**",
        f"- Cron active: **{summary.get('cron_active', False)}**",
        "",
        "## Checks",
        "",
    ]
    for chk in report.get("checks") or []:
        if not isinstance(chk, Mapping):
            continue
        st = str(chk.get("status") or "").upper()
        name = chk.get("name") or "?"
        msg = chk.get("message") or ""
        lines.append(f"- [{st}] `{name}`: {msg}")
    lines.append("")
    return "\n".join(lines)


def write_healthcheck_outputs(
    report: Mapping[str, Any],
    *,
    md_path: Path,
    json_path: Path,
) -> tuple[Path, Path]:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_healthcheck_md(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return md_path, json_path
