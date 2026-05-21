"""Phase 29 — observation metrics aggregator tests (fixtures, no network)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.aggregate_observation_metrics_phase29 import (
    aggregate_all,
    aggregate_target_metrics,
    render_monitoring_md,
    write_outputs,
)


def _write_fixture_state(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "asset": "ETH",
                "timeframe": "4h",
                "strategy": "trend_following+funding_basis",
                "cash_usd": 1050.0,
                "equity": 1050.0,
                "iteration": 3,
                "mode": "observation_only",
                "last_processed_timestamp": 1000,
            }
        ),
        encoding="utf-8",
    )
    (state_dir / "equity_curve.csv").write_text(
        "timestamp,equity\n900,1000.0\n950,1020.0\n1000,1050.0\n",
        encoding="utf-8",
    )
    (state_dir / "trades.csv").write_text(
        "bar_index,side,symbol,timestamp\n1,buy,ETH,900\n2,sell,ETH,950\n",
        encoding="utf-8",
    )
    decisions = [
        {
            "timestamp": 900,
            "observation_only": True,
            "overlay_decision": "allow",
            "derivatives_status": "available",
        },
        {
            "timestamp": 950,
            "observation_only": True,
            "overlay_decision": "block",
            "derivatives_status": "available",
        },
        {
            "timestamp": 1000,
            "observation_only": True,
            "overlay_decision": "reduce",
            "derivatives_status": "available",
        },
    ]
    with (state_dir / "decisions.jsonl").open("w", encoding="utf-8") as fh:
        for row in decisions:
            fh.write(json.dumps(row) + "\n")

    shadows = [
        {
            "timestamp": 900,
            "price": 100.0,
            "standalone_would_trade": True,
            "overlay_blocks": True,
            "overlay_decision": "block",
        },
        {
            "timestamp": 950,
            "price": 110.0,
            "standalone_would_trade": False,
            "overlay_blocks": False,
            "overlay_decision": "allow",
        },
        {
            "timestamp": 1000,
            "price": 105.0,
            "standalone_would_trade": True,
            "overlay_blocks": True,
            "overlay_decision": "block",
        },
    ]
    with (state_dir / "shadow_comparison.jsonl").open("w", encoding="utf-8") as fh:
        for row in shadows:
            fh.write(json.dumps(row) + "\n")


def test_aggregate_target_metrics_on_fixture(tmp_path: Path) -> None:
    state = tmp_path / "trend_following_baseline"
    _write_fixture_state(state)
    metrics = aggregate_target_metrics(state)
    assert metrics["decision_count"] == 3
    assert metrics["trade_count"] == 2
    assert metrics["overlay_decisions"]["block"] == 1
    assert metrics["overlay_decisions"]["reduce"] == 1
    assert metrics["observation_only"] is True
    assert metrics["equity"]["overlay_usd"] == 1050.0
    assert metrics["shadow_proxies"]["missed_upside_bars"] >= 0


def test_aggregate_all_two_targets(tmp_path: Path) -> None:
    base = tmp_path / "paper_observation_phase28"
    for name in ("trend_following_baseline", "ema_crossover_baseline"):
        _write_fixture_state(base / name)
    payload = aggregate_all(base)
    assert payload["summary"]["target_count"] == 2
    assert payload["summary"]["total_decisions"] == 6
    assert payload["stop_observation_active"] is False
    md = render_monitoring_md(payload)
    assert "PAPER OBSERVATION ONLY" in md


def test_write_outputs(tmp_path: Path) -> None:
    base = tmp_path / "paper_observation_phase28"
    _write_fixture_state(base / "trend_following_baseline")
    _write_fixture_state(base / "ema_crossover_baseline")
    payload = aggregate_all(base)
    json_path = tmp_path / "metrics" / "summary.json"
    md_path = tmp_path / "monitoring.md"
    write_outputs(payload, json_path=json_path, md_path=md_path)
    assert json_path.is_file()
    assert md_path.is_file()
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["phase"] == 29
