"""Phase 30.3 — observation alerts tests."""

from __future__ import annotations

import json
from pathlib import Path

from src.bot.observation_alerts import collect_observation_alerts, render_alerts_md
from src.bot.overlay_observation_kill import STANDALONE_EVALUATED


def _write_summary(
    path: Path,
    *,
    block_rate: float = 0.0,
    stale: int = 0,
    overlay_ret: float | None = 5.0,
    standalone_ret: float | None = 10.0,
    standalone_status: str = STANDALONE_EVALUATED,
    standalone_reason: str = "",
) -> None:
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
                            "overlay_return_pct_from_1k": overlay_ret,
                            "standalone_return_pct": standalone_ret,
                            "standalone_status": standalone_status,
                            "standalone_status_reason": standalone_reason,
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


def test_overlay_underperformance_triggers_warning(tmp_path: Path) -> None:
    """La branche standalone n'est plus morte: elle se declenche reellement."""
    obs = tmp_path / "obs"
    obs.mkdir()
    summary = tmp_path / "summary.json"
    _write_summary(summary, overlay_ret=5.0, standalone_ret=10.0)
    report = collect_observation_alerts(observation_base=obs, summary_path=summary)
    alert = next(
        a for a in report.alerts if a.code == "overlay_underperforms_standalone"
    )
    assert alert.severity == "warning"
    assert alert.target == "trend_following_baseline"


def test_overlay_outperformance_no_warning(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    summary = tmp_path / "summary.json"
    _write_summary(summary, overlay_ret=12.0, standalone_ret=10.0)
    report = collect_observation_alerts(observation_base=obs, summary_path=summary)
    codes = [a.code for a in report.alerts]
    assert "overlay_underperforms_standalone" not in codes
    assert "standalone_comparison_not_evaluable" not in codes


def test_legacy_available_status_is_not_trusted(tmp_path: Path) -> None:
    """Un summary.json anterieur a la Phase 30.5 ne doit pas produire de warning.

    Ces fichiers portent ``standalone_status="available"`` avec un rendement
    calcule sur une courbe qui n'est PAS homogene a la courbe overlay (l'une
    repart de zero a chaque run, l'autre compose). Comparer les deux chiffres
    produirait un ``overlay_underperforms_standalone`` sans fondement : seul le
    statut ``evaluated`` autorise la comparaison.
    """
    obs = tmp_path / "obs"
    obs.mkdir()
    summary = tmp_path / "summary.json"
    _write_summary(
        summary, overlay_ret=5.0, standalone_ret=10.0, standalone_status="available"
    )
    report = collect_observation_alerts(observation_base=obs, summary_path=summary)
    codes = [a.code for a in report.alerts]
    assert "overlay_underperforms_standalone" not in codes
    assert "standalone_comparison_not_evaluable" in codes


def test_standalone_not_evaluable_is_explicit(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    summary = tmp_path / "summary.json"
    _write_summary(
        summary,
        standalone_ret=None,
        standalone_status="not_evaluable",
        standalone_reason="standalone_equity.csv absent in trend_following_baseline",
    )
    report = collect_observation_alerts(observation_base=obs, summary_path=summary)
    alert = next(
        a for a in report.alerts if a.code == "standalone_comparison_not_evaluable"
    )
    assert alert.severity == "info"
    assert "standalone_equity.csv absent" in alert.message


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
