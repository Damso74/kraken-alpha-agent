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
from src.bot.overlay_observation_kill import (
    STANDALONE_EVALUATED,
    STANDALONE_NOT_EVALUABLE,
    STANDALONE_REASON_HETEROGENEOUS,
    STANDALONE_REASON_MISSING,
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


def _write_standalone_curve(state_dir: Path, values: list[float]) -> None:
    lines = ["timestamp,equity"]
    lines += [f"{900 + i * 50},{v}" for i, v in enumerate(values)]
    (state_dir / "standalone_equity.csv").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def test_standalone_return_not_evaluable_without_curve(tmp_path: Path) -> None:
    """Sans standalone_equity.csv le critere est explicitement non evaluable."""
    state = tmp_path / "trend_following_baseline"
    _write_fixture_state(state)
    metrics = aggregate_target_metrics(state)
    assert metrics["equity"]["standalone_return_pct"] is None
    assert metrics["equity"]["standalone_status"] == STANDALONE_NOT_EVALUABLE
    assert metrics["equity"]["standalone_status_reason"] == STANDALONE_REASON_MISSING
    assert metrics["equity"]["standalone_status_detail"]
    comparison = metrics["kill_criteria"]["metrics"]["standalone_comparison"]
    assert comparison["status"] == STANDALONE_NOT_EVALUABLE
    assert comparison["reason"] == STANDALONE_REASON_MISSING


def test_run_level_standalone_curve_is_never_compared(tmp_path: Path) -> None:
    """La comparaison inter-runs est refusee: courbes heterogenes (residu #1).

    equity_curve.csv compose le rendement de la serie a chaque run cron alors que
    standalone_equity.csv repart de cfg.cash: un standalone apparemment gagnant
    (+20%) ne doit plus produire ni return_pct ni declenchement du critere de kill.
    """
    state = tmp_path / "trend_following_baseline"
    _write_fixture_state(state)
    _write_standalone_curve(state, [1000.0, 1100.0, 1200.0])
    metrics = aggregate_target_metrics(state)
    assert metrics["equity"]["standalone_return_pct"] is None
    assert metrics["equity"]["standalone_usd"] == 1200.0
    assert metrics["equity"]["standalone_status"] == STANDALONE_NOT_EVALUABLE
    assert (
        metrics["equity"]["standalone_status_reason"] == STANDALONE_REASON_HETEROGENEOUS
    )
    kill = metrics["kill_criteria"]
    assert kill["metrics"]["standalone_comparison"]["status"] == STANDALONE_NOT_EVALUABLE
    assert kill["metrics"]["equity_gap_pct"] is None
    assert not any("overlay_underperforms_standalone" in r for r in kill["reasons"])


def test_run_level_standalone_curve_cannot_falsely_kill(tmp_path: Path) -> None:
    """Symetrique: un standalone plat face a un overlay composé ne kill pas non plus."""
    state = tmp_path / "trend_following_baseline"
    _write_fixture_state(state)
    _write_standalone_curve(state, [1000.0, 1000.0, 1000.0])
    kill = aggregate_target_metrics(state)["kill_criteria"]
    assert kill["metrics"]["standalone_comparison"]["status"] == STANDALONE_NOT_EVALUABLE
    assert not any("overlay_underperforms_standalone" in r for r in kill["reasons"])


def test_summary_and_kill_agree_on_standalone_verdict(tmp_path: Path) -> None:
    """Un seul verdict par document (residu #2).

    Le cas historiquement contradictoire est celui d'UN SEUL point persiste:
    summary.json annoncait standalone_status="available" avec un return_pct chiffre
    pendant que kill_criteria disait not_evaluable (curve_too_short).
    """
    for values in ([1050.0], [1000.0, 1100.0, 1200.0], []):
        state = tmp_path / f"trend_following_baseline_{len(values)}"
        _write_fixture_state(state)
        if values:
            _write_standalone_curve(state, values)
        metrics = aggregate_target_metrics(state)
        equity = metrics["equity"]
        comparison = metrics["kill_criteria"]["metrics"]["standalone_comparison"]
        assert equity["standalone_status"] == comparison["status"], values
        assert equity["standalone_status_reason"] == comparison["reason"], values
        assert equity["standalone_status"] in {
            STANDALONE_EVALUATED,
            STANDALONE_NOT_EVALUABLE,
        }
        if equity["standalone_status"] != STANDALONE_EVALUATED:
            assert equity["standalone_return_pct"] is None, values


def test_starting_equity_is_not_hardcoded(tmp_path: Path) -> None:
    """Residu #3: le denominateur des rendements suit le capital reel."""
    state = tmp_path / "trend_following_baseline"
    _write_fixture_state(state)  # state.json: equity = 1050.0
    default_metrics = aggregate_target_metrics(state)
    assert default_metrics["equity"]["starting_equity_usd"] == 1000.0
    assert default_metrics["equity"]["overlay_return_pct_from_1k"] == 5.0

    metrics = aggregate_target_metrics(state, starting_equity=500.0)
    assert metrics["equity"]["starting_equity_usd"] == 500.0
    assert metrics["equity"]["overlay_return_pct_from_1k"] == 110.0


def test_aggregate_all_propagates_starting_equity(tmp_path: Path) -> None:
    base = tmp_path / "paper_observation_phase28"
    for name in ("trend_following_baseline", "ema_crossover_baseline"):
        _write_fixture_state(base / name)
    payload = aggregate_all(base, starting_equity=2000.0)
    for target in payload["targets"]:
        assert target["equity"]["starting_equity_usd"] == 2000.0
        assert target["equity"]["overlay_return_pct_from_1k"] == -47.5
    assert "(return from 2000: -47.5%)" in render_monitoring_md(payload)


def test_monitoring_md_reports_standalone_status(tmp_path: Path) -> None:
    base = tmp_path / "paper_observation_phase28"
    for name in ("trend_following_baseline", "ema_crossover_baseline"):
        _write_fixture_state(base / name)
    _write_standalone_curve(base / "trend_following_baseline", [1000.0, 1010.0, 1020.0])
    md = render_monitoring_md(aggregate_all(base))
    assert f"- Standalone return: {STANDALONE_NOT_EVALUABLE} " in md
    assert STANDALONE_REASON_HETEROGENEOUS in md
    assert STANDALONE_REASON_MISSING in md
    assert "%" not in md.split("### Equity")[1].split("- Standalone return: ")[1].split("\n")[0]


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
