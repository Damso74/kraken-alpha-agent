"""Phase 30.2 — observation dashboard generator tests."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_observation_dashboard_phase30 import build_dashboard_html, write_dashboard


def _minimal_summary() -> dict:
    return {
        "generated_at_utc": "2026-05-21T12:00:00+00:00",
        "summary": {
            "target_count": 1,
            "total_decisions": 1,
            "total_trades": 0,
            "any_kill_triggered": False,
        },
        "targets": [
            {
                "target": "trend_following_baseline",
                "decision_count": 1,
                "trade_count": 0,
                "block_rate_on_signals": 0.0,
                "stale_data_count": 0,
                "error_count": 0,
                "overlay_decisions": {"allow": 1, "block": 0, "reduce": 0, "neutral": 0},
                "equity": {"overlay_usd": 1000.0, "overlay_return_pct_from_1k": 0.0},
                "shadow_proxies": {"blocks": 0, "reductions": 0, "missed_upside_bars": 0},
                "kill_criteria": {"should_kill": False, "reasons": []},
            }
        ],
    }


def test_build_dashboard_contains_expected_sections(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    summary_dir = tmp_path / "metrics"
    summary_dir.mkdir()
    summary_path = summary_dir / "summary.json"
    summary_path.write_text(json.dumps(_minimal_summary()), encoding="utf-8")

    html_doc = build_dashboard_html(observation_base=obs, summary_path=summary_path)
    for section_id in (
        "status",
        "stop",
        "freshness",
        "targets",
        "equity",
        "overlay",
        "risk",
        "decisions",
        "kill",
        "next",
    ):
        assert f'id="{section_id}"' in html_doc
    assert "external" not in html_doc.lower() or "no external" in html_doc.lower()
    assert "<script" not in html_doc


def test_write_dashboard_minimal_data_no_crash(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    out = obs / "dashboard.html"
    write_dashboard(out, observation_base=obs, summary_path=summary_path)
    content = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "Observation Ops Dashboard" in content
