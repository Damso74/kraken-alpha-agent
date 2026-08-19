"""Phase 30.3 — observation ops alerts (no secrets, no live I/O)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.bot.observation_ops_guards import check_all_target_state_warnings
from src.bot.observation_state_migration import TARGET_METADATA
from src.bot.overlay_observation_engine import PHASE28_TARGETS, default_state_dir
from src.bot.overlay_observation_kill import STANDALONE_EVALUATED

DEFAULT_BASE = Path("reports/paper_observation_phase28")
DEFAULT_SUMMARY = Path("reports/phase29_observation_metrics/summary.json")
BLOCK_RATE_THRESHOLD = 0.60


@dataclass
class Alert:
    code: str
    severity: str  # critical | warning | info
    message: str
    target: str = ""


@dataclass
class AlertReport:
    generated_at_utc: str = ""
    alerts: list[Alert] = field(default_factory=list)
    critical_count: int = 0
    warning_count: int = 0
    exit_code_recommended: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "exit_code_recommended": self.exit_code_recommended,
            "alerts": [asdict(a) for a in self.alerts],
        }


def _latest_ops_log(ops_logs: Path) -> Path | None:
    if not ops_logs.is_dir():
        return None
    logs = sorted(ops_logs.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _load_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _count_decisions(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())


def collect_observation_alerts(
    *,
    observation_base: Path = DEFAULT_BASE,
    summary_path: Path = DEFAULT_SUMMARY,
    report_generation_failed: bool = False,
) -> AlertReport:
    """Evaluate alert conditions from on-disk observation artifacts."""
    report = AlertReport(generated_at_utc=datetime.now(UTC).isoformat())
    alerts = report.alerts

    stop_flag = observation_base / "STOP_OBSERVATION"
    if stop_flag.is_file():
        reason = stop_flag.read_text(encoding="utf-8").strip() or "manual stop"
        alerts.append(
            Alert(
                code="stop_observation",
                severity="critical",
                message=f"STOP_OBSERVATION active: {reason}",
            )
        )

    summary = _load_summary(summary_path)
    if not summary:
        alerts.append(
            Alert(
                code="missing_summary",
                severity="warning",
                message=f"summary.json missing or empty: {summary_path}",
            )
        )

    state_dirs = [
        default_state_dir(observation_base, s, v) for s, v, _ in PHASE28_TARGETS
    ]
    for msg in check_all_target_state_warnings(state_dirs):
        alerts.append(
            Alert(
                code="state_legacy",
                severity="warning",
                message=msg,
                target=msg.split(":")[0] if ":" in msg else "",
            )
        )

    for target in summary.get("targets") or []:
        if not isinstance(target, Mapping):
            continue
        name = str(target.get("target") or "")
        block_rate = float(target.get("block_rate_on_signals") or 0.0)
        if block_rate > BLOCK_RATE_THRESHOLD:
            alerts.append(
                Alert(
                    code="high_block_rate",
                    severity="warning",
                    message=f"block_rate_on_signals={block_rate:.1%} > {BLOCK_RATE_THRESHOLD:.0%}",
                    target=name,
                )
            )

        stale_count = int(target.get("stale_data_count") or 0)
        if stale_count > 0:
            alerts.append(
                Alert(
                    code="stale_data",
                    severity="warning",
                    message=f"stale_data_count={stale_count}",
                    target=name,
                )
            )

        equity = target.get("equity") or {}
        overlay_ret = equity.get("overlay_return_pct_from_1k")
        standalone_ret = equity.get("standalone_return_pct")
        standalone_status = str(equity.get("standalone_status") or "")
        # Le verdict fait autorite, pas la seule presence d'un chiffre: un summary.json
        # ancien porte encore standalone_status="available" avec un return_pct calcule
        # sur une courbe NON homogene a la courbe overlay (cf. _standalone_summary,
        # Phase 30.5). Comparer ces deux rendements produirait un warning faux.
        if standalone_ret is None or standalone_status != STANDALONE_EVALUATED:
            reason = str(
                equity.get("standalone_status_reason") or "standalone curve unavailable"
            )
            alerts.append(
                Alert(
                    code="standalone_comparison_not_evaluable",
                    severity="info",
                    message=f"overlay vs standalone not evaluable: {reason}",
                    target=name,
                )
            )
        elif overlay_ret is not None and float(overlay_ret) < float(standalone_ret):
            alerts.append(
                Alert(
                    code="overlay_underperforms_standalone",
                    severity="warning",
                    message=(
                        f"overlay_return={overlay_ret}% < standalone_return={standalone_ret}%"
                    ),
                    target=name,
                )
            )

        errors_tail = target.get("errors_tail") or []
        if errors_tail:
            alerts.append(
                Alert(
                    code="target_errors",
                    severity="warning",
                    message=f"errors in tail: {errors_tail[-1]}",
                    target=name,
                )
            )

        if target.get("kill_criteria", {}).get("should_kill"):
            reasons = target.get("kill_criteria", {}).get("reasons") or []
            alerts.append(
                Alert(
                    code="kill_criteria",
                    severity="critical",
                    message=f"kill criteria triggered: {', '.join(reasons)}",
                    target=name,
                )
            )

    ops_logs = observation_base / "ops_logs"
    latest_log = _latest_ops_log(ops_logs)
    if latest_log:
        log_text = latest_log.read_text(encoding="utf-8", errors="replace")
        error_lines = [
            ln.strip()
            for ln in log_text.splitlines()
            if "Traceback" in ln or " ERROR" in ln.upper() or "Error:" in ln
        ]
        if error_lines:
            alerts.append(
                Alert(
                    code="ops_log_errors",
                    severity="warning",
                    message=f"{len(error_lines)} error line(s) in {latest_log.name}",
                )
            )
    else:
        alerts.append(
            Alert(
                code="no_ops_logs",
                severity="info",
                message="no ops_logs/*.log found yet",
            )
        )

    for target_id in TARGET_METADATA:
        state_dir = observation_base / target_id
        dc = _count_decisions(state_dir / "decisions.jsonl")
        if dc <= 1:
            alerts.append(
                Alert(
                    code="no_new_candle",
                    severity="info",
                    message=(
                        f"decision_count={dc} — duplicate-candle idempotence or awaiting next 4h bar"
                    ),
                    target=target_id,
                )
            )

    if report_generation_failed:
        alerts.append(
            Alert(
                code="report_generation_failed",
                severity="critical",
                message="dashboard or alerts generation failed in ops pipeline",
            )
        )

    report.critical_count = sum(1 for a in alerts if a.severity == "critical")
    report.warning_count = sum(1 for a in alerts if a.severity == "warning")
    # Cron stability: exit 0 unless STOP flag (documented policy)
    report.exit_code_recommended = 1 if stop_flag.is_file() else 0
    return report


def render_alerts_md(report: AlertReport) -> str:
    lines = [
        "# Observation alerts (Phase 30.3)",
        "",
        f"> Generated: {report.generated_at_utc} UTC",
        "",
        f"- Critical: **{report.critical_count}**",
        f"- Warning: **{report.warning_count}**",
        f"- Recommended exit code (cron): **{report.exit_code_recommended}** "
        "(0 for cron stability unless STOP_OBSERVATION)",
        "",
    ]
    if not report.alerts:
        lines.append("No alerts — observation ops nominal.")
        lines.append("")
        return "\n".join(lines)

    for alert in report.alerts:
        prefix = f"[{alert.severity.upper()}]"
        target = f" ({alert.target})" if alert.target else ""
        lines.append(f"- {prefix} `{alert.code}`{target}: {alert.message}")
    lines.append("")
    return "\n".join(lines)


def write_alert_outputs(
    report: AlertReport,
    *,
    md_path: Path,
    json_path: Path,
) -> tuple[Path, Path]:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_alerts_md(report), encoding="utf-8")
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return md_path, json_path
