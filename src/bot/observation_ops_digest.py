"""Phase 30.4 — observation ops digest (dry-run notification rollup)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.bot.observation_healthcheck import find_latest_log, load_json

DEFAULT_BASE = Path("reports/paper_observation_phase28")
DEFAULT_SUMMARY = Path("reports/phase29_observation_metrics/summary.json")


def resolve_next_action(
    *,
    alerts: Mapping[str, Any],
    health: Mapping[str, Any],
    summary: Mapping[str, Any] | None = None,
    stop_active: bool,
    log_age_hours: float | None,
    max_log_fail_hours: float = 6.0,
) -> str:
    """Pick operator next_action from alerts + health state."""
    if stop_active:
        return "stop_observation"
    if int(alerts.get("critical_count") or 0) > 0:
        return "fix_required"

    alert_rows = alerts.get("alerts") or []
    has_stale = any(
        isinstance(a, Mapping) and a.get("code") == "stale_data"
        for a in alert_rows
    )
    if has_stale:
        return "fix_required"

    for target in (summary or {}).get("targets") or []:
        if isinstance(target, Mapping) and int(target.get("stale_data_count") or 0) > 0:
            return "fix_required"

    if log_age_hours is not None and log_age_hours > max_log_fail_hours:
        return "check_vps_cron"

    health_status = str(health.get("status") or "")
    if health_status == "fail":
        checks = health.get("checks") or []
        for chk in checks:
            if not isinstance(chk, Mapping):
                continue
            if chk.get("name") == "ops_log_freshness" and chk.get("status") == "fail":
                return "check_vps_cron"
        return "fix_required"

    if alert_rows:
        only_no_candle = all(
            isinstance(a, Mapping)
            and a.get("code") == "no_new_candle"
            and a.get("severity") == "info"
            for a in alert_rows
        )
        if only_no_candle:
            return "continue_observation"

    if health_status == "warning":
        for chk in health.get("checks") or []:
            if isinstance(chk, Mapping) and chk.get("name") == "ops_log_freshness":
                if chk.get("status") in ("fail", "warning"):
                    return "check_vps_cron"

    return "continue_observation"


def _latest_weekly_md(base: Path) -> Path | None:
    files = sorted(base.glob("weekly_summary_*.md"), reverse=True)
    return files[0] if files else None


def build_ops_digest(
    *,
    observation_base: Path = DEFAULT_BASE,
    summary_path: Path = DEFAULT_SUMMARY,
    alerts_path: Path | None = None,
    health_path: Path | None = None,
) -> dict[str, Any]:
    alerts_path = alerts_path or observation_base / "alerts.json"
    health_path = health_path or observation_base / "healthcheck.json"

    summary = load_json(summary_path)
    alerts = load_json(alerts_path)
    health = load_json(health_path)
    stop_path = observation_base / "STOP_OBSERVATION"
    stop_active = stop_path.is_file()

    latest_log = find_latest_log(observation_base / "ops_logs")
    log_age_h: float | None = None
    if latest_log is not None:
        try:
            age_sec = datetime.now(UTC).timestamp() - latest_log.stat().st_mtime
            log_age_h = age_sec / 3600.0
        except OSError:
            log_age_h = None

    next_action = resolve_next_action(
        alerts=alerts,
        health=health,
        summary=summary,
        stop_active=stop_active,
        log_age_hours=log_age_h,
    )

    targets_rows: list[dict[str, Any]] = []
    for t in summary.get("targets") or []:
        if not isinstance(t, Mapping):
            continue
        equity = t.get("equity") or {}
        targets_rows.append(
            {
                "target": t.get("target"),
                "decision_count": t.get("decision_count"),
                "trade_count": t.get("trade_count"),
                "stale_data_count": t.get("stale_data_count"),
                "overlay_return_pct": equity.get("overlay_return_pct_from_1k"),
                "block_rate": t.get("block_rate_on_signals"),
            }
        )

    alert_lines = [
        {
            "code": a.get("code"),
            "severity": a.get("severity"),
            "message": a.get("message"),
            "target": a.get("target"),
        }
        for a in alerts.get("alerts") or []
        if isinstance(a, Mapping)
    ]

    weekly = _latest_weekly_md(observation_base)
    health_status = str(health.get("status") or "unknown")
    overall_status = health_status
    if stop_active:
        overall_status = "fail"
    elif int(alerts.get("critical_count") or 0) > 0:
        overall_status = "fail"

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": overall_status,
        "next_action": next_action,
        "stop_observation_active": stop_active,
        "healthcheck_status": health_status,
        "alerts_critical_count": int(alerts.get("critical_count") or 0),
        "alerts_warning_count": int(alerts.get("warning_count") or 0),
        "latest_ops_log": latest_log.name if latest_log else None,
        "latest_ops_log_age_hours": round(log_age_h, 2) if log_age_h is not None else None,
        "dashboard_path": str(observation_base / "dashboard.html"),
        "weekly_summary": weekly.name if weekly else None,
        "targets": targets_rows,
        "alerts": alert_lines,
    }


def render_ops_digest_md(digest: Mapping[str, Any]) -> str:
    status = str(digest.get("status") or "unknown").upper()
    next_action = str(digest.get("next_action") or "continue_observation")
    lines = [
        "# Observation ops digest (Phase 30.4)",
        "",
        f"> Generated: {digest.get('generated_at_utc', '')} UTC",
        "",
        "## Status",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Overall | `{status}` |",
        f"| Healthcheck | `{digest.get('healthcheck_status', '')}` |",
        f"| Next action | **`{next_action}`** |",
        f"| STOP flag | {digest.get('stop_observation_active')} |",
        f"| Critical alerts | {digest.get('alerts_critical_count')} |",
        f"| Warning alerts | {digest.get('alerts_warning_count')} |",
        f"| Latest ops log | {digest.get('latest_ops_log') or '—'} |",
        f"| Log age (h) | {digest.get('latest_ops_log_age_hours', '—')} |",
        "",
        "## Targets",
        "",
        "| Target | Decisions | Trades | Stale | Overlay ret % | Block rate |",
        "|--------|-----------|--------|-------|---------------|------------|",
    ]
    for row in digest.get("targets") or []:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"| {row.get('target', '')} | {row.get('decision_count', '')} | "
            f"{row.get('trade_count', '')} | {row.get('stale_data_count', '')} | "
            f"{row.get('overlay_return_pct', '')} | {row.get('block_rate', '')} |"
        )
    lines.extend(["", "## Alerts", ""])
    alerts = digest.get("alerts") or []
    if not alerts:
        lines.append("No alerts — nominal.")
    else:
        for a in alerts:
            if not isinstance(a, Mapping):
                continue
            sev = str(a.get("severity") or "").upper()
            code = a.get("code") or ""
            tgt = f" ({a['target']})" if a.get("target") else ""
            lines.append(f"- [{sev}] `{code}`{tgt}: {a.get('message', '')}")
    lines.extend(
        [
            "",
            "## Next action",
            "",
            f"**`{next_action}`** — dry-run notification only (no email/webhook).",
            "",
        ]
    )
    weekly = digest.get("weekly_summary")
    if weekly:
        lines.append(f"Weekly rollup: `{weekly}`")
        lines.append("")
    return "\n".join(lines)


def write_ops_digest_outputs(
    digest: Mapping[str, Any],
    *,
    md_path: Path,
    json_path: Path,
) -> tuple[Path, Path]:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_ops_digest_md(digest), encoding="utf-8")
    json_path.write_text(json.dumps(digest, indent=2), encoding="utf-8")
    return md_path, json_path
