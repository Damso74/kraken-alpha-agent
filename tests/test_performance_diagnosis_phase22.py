"""Phase 22 performance diagnosis — hermetic script tests (no network)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts._phase22_common import (
    fee_interpretation,
    run_backtest_cell,
    strategy_family,
)
from scripts.analyze_timeframe_turnover_phase22 import (
    cost_drag_stats,
    format_cost_drag_line,
)
from src.data.collectors.binance_public import (
    MIN_ROWS_DATA_OK,
    default_ohlc_cache_path,
    save_ohlc_cache,
)

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable

SCRIPTS = (
    "run_fee_sensitivity_phase22.py",
    "run_risk_sensitivity_phase22.py",
    "analyze_timeframe_turnover_phase22.py",
    "benchmark_regime_router_phase22.py",
    "generate_strategy_family_autopsy_phase22.py",
    "generate_phase22_reports.py",
)


def _make_candles(*, count: int, step_seconds: int) -> list[dict]:
    start_ts = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    out: list[dict] = []
    for i in range(count):
        ts = start_ts + i * step_seconds
        close = 50_000.0 + i * 0.01
        out.append(
            {
                "timestamp": ts,
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "vwap": close,
                "volume": 10.0 + i,
            }
        )
    return out


def _seed_cache(tmp_path: Path, asset: str = "BTC") -> Path:
    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    for tf, step in (("1d", 86400), ("4h", 14400), ("1h", 3600)):
        rows = _make_candles(count=MIN_ROWS_DATA_OK[tf] + 20, step_seconds=step)
        path = cache_root / default_ohlc_cache_path(asset, tf).name
        save_ohlc_cache(path, ticker=asset, timeframe=tf, rows=rows)
    return cache_root


@pytest.mark.parametrize("script", SCRIPTS)
def test_script_help(script: str) -> None:
    proc = subprocess.run(
        [PY, str(REPO / "scripts" / script), "--help"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout.lower() or "Phase 22" in proc.stdout


def test_strategy_family_mapping() -> None:
    assert strategy_family("trend_following") == "trend_ema_donchian"
    assert strategy_family("atr_breakout") == "breakout_atr"
    assert strategy_family("grid") == "grid"


def test_fee_interpretation_labels() -> None:
    assert fee_interpretation(-1.0, -2.0, -3.0) == "no_edge_at_zero_fees"
    assert fee_interpretation(5.0, 2.0, -2.0) == "killed_by_costs"
    assert fee_interpretation(3.0, -1.0, -2.0) == "cost_sensitive_survives_moderate"


def test_run_backtest_cell_hermetic(tmp_path: Path) -> None:
    cache_root = _seed_cache(tmp_path)
    row = run_backtest_cell(
        "BTC",
        "1d",
        "trend_following",
        fees_bps=0.0,
        slippage_bps=0.0,
        cache_root=cache_root,
    )
    assert row["asset"] == "BTC"
    assert row["data_ok"] is True
    assert "verdict" in row
    assert "turnover_ratio" in row


def test_fee_sensitivity_fast(tmp_path: Path) -> None:
    cache_root = _seed_cache(tmp_path)
    out = tmp_path / "fee_out"
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "run_fee_sensitivity_phase22.py"),
            "--fast",
            "--cache-root",
            str(cache_root),
            "--output-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert payload["fast_mode"] is True
    assert len(payload["runs"]) == 3 * 4 * 3  # 3 strats × fee grid × slip grid


def test_risk_sensitivity_fast(tmp_path: Path) -> None:
    cache_root = _seed_cache(tmp_path)
    out = tmp_path / "risk_out"
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"runs": []}), encoding="utf-8")
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "run_risk_sensitivity_phase22.py"),
            "--fast",
            "--cache-root",
            str(cache_root),
            "--baseline-results",
            str(baseline),
            "--output-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (out / "summary.json").is_file()


def test_benchmark_regime_router_fast(tmp_path: Path) -> None:
    cache_root = _seed_cache(tmp_path)
    out = tmp_path / "bench_out"
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "benchmark_regime_router_phase22.py"),
            "--fast",
            "--timeframe",
            "4h",
            "--cache-root",
            str(cache_root),
            "--output-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    bench = json.loads((out / "benchmark.json").read_text(encoding="utf-8"))
    assert "uncached" in bench and "cached" in bench
    assert bench["speedup_x"] > 0


def test_precompute_regime_features() -> None:
    from src.bot.regime_features import precompute_regime_features

    candles = _make_candles(count=120, step_seconds=3600)
    feats = precompute_regime_features(candles, ma_window=50)
    assert len(feats) == len(candles)
    assert feats[0] is None
    assert feats[-1] is not None


# ---------------------------------------------------------------------------
# cost drag : la sentinelle 100 % a ete supprimee de src.bot.metrics, il ne
# faut pas la remplacer par un 0.0 agrege qui dirait "les frais sont gratuits".
# ---------------------------------------------------------------------------


def test_cost_drag_stats_excludes_undefined_rows() -> None:
    items = [
        {"cost_drag_pct": 10.0, "cost_drag_undefined": False},
        {"cost_drag_pct": 30.0, "cost_drag_undefined": False},
        # remplissage : sans aller-retour ferme le ratio n'existe pas
        {"cost_drag_pct": 0.0, "cost_drag_undefined": True},
        {"cost_drag_pct": 0.0, "cost_drag_undefined": True},
    ]
    stats = cost_drag_stats(items)
    assert stats["median_cost_drag_pct"] == 20.0  # et non 5.0 (mediane des 4)
    assert stats["cost_drag_runs_total"] == 4
    assert stats["cost_drag_measurable_runs"] == 2
    assert stats["cost_drag_undefined_runs"] == 2
    assert stats["cost_drag_unflagged_runs"] == 0


def test_cost_drag_stats_is_none_when_every_run_is_undefined() -> None:
    items = [{"cost_drag_pct": 0.0, "cost_drag_undefined": True} for _ in range(3)]
    stats = cost_drag_stats(items)
    assert stats["median_cost_drag_pct"] is None
    assert stats["cost_drag_measurable_runs"] == 0
    assert stats["cost_drag_undefined_runs"] == 3


def test_cost_drag_stats_excludes_rows_without_the_flag() -> None:
    """Un run sans la cle ne prouve rien : ni mesure ni indefini."""
    items = [
        {"cost_drag_pct": 12.0, "cost_drag_undefined": False},
        {"cost_drag_pct": 100.0},  # artefact anterieur au correctif
    ]
    stats = cost_drag_stats(items)
    assert stats["median_cost_drag_pct"] == 12.0
    assert stats["cost_drag_unflagged_runs"] == 1
    assert stats["cost_drag_measurable_runs"] == 1


def test_format_cost_drag_line_states_the_denominator() -> None:
    line = format_cost_drag_line(
        {
            "median_cost_drag_pct": 20.0,
            "cost_drag_runs_total": 4,
            "cost_drag_measurable_runs": 2,
            "cost_drag_undefined_runs": 2,
            "cost_drag_unflagged_runs": 0,
        }
    )
    assert "20.0%" in line
    assert "median calculee sur 2/4 runs" in line
    assert "2 runs sans aller-retour ferme" in line


def test_format_cost_drag_line_says_na_when_nothing_is_measurable() -> None:
    line = format_cost_drag_line(
        {
            "median_cost_drag_pct": None,
            "cost_drag_runs_total": 3,
            "cost_drag_measurable_runs": 0,
            "cost_drag_undefined_runs": 3,
            "cost_drag_unflagged_runs": 0,
        }
    )
    assert "n/a" in line
    assert "0.0%" not in line
    assert "median calculee sur 0/3 runs" in line


def _turnover_row(*, cost_drag_pct: float, undefined: bool) -> dict:
    return {
        "asset": "BTC",
        "timeframe": "1h",
        "strategy": "trend_following",
        "verdict": "blocked_costs",
        "total_return_pct": -1.0,
        "trade_count": 4,
        "cost_drag_pct": cost_drag_pct,
        "cost_drag_undefined": undefined,
        "turnover_ratio": 0.5,
    }


def test_timeframe_turnover_report_does_not_publish_a_zero_cost_drag(tmp_path: Path) -> None:
    """Bout en bout : le markdown ne doit pas annoncer 0.0 % de frais."""
    src = tmp_path / "runs.json"
    src.write_text(
        json.dumps(
            {
                "runs": [
                    _turnover_row(cost_drag_pct=40.0, undefined=False),
                    _turnover_row(cost_drag_pct=0.0, undefined=True),
                    _turnover_row(cost_drag_pct=0.0, undefined=True),
                ]
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "tf_out"
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "analyze_timeframe_turnover_phase22.py"),
            "--input",
            str(src),
            "--output-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    summary_md = (out / "summary.md").read_text(encoding="utf-8")
    assert "Median cost drag: 40.0%" in summary_md
    assert "median calculee sur 1/3 runs" in summary_md
    assert "2 runs sans aller-retour ferme" in summary_md
    assert "Median cost drag: 0.0%" not in summary_md

    payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
    tf_stats = payload["by_timeframe"]["1h"]
    assert tf_stats["median_cost_drag_pct"] == 40.0
    assert tf_stats["cost_drag_undefined_runs"] == 2
    fam_stats = payload["by_family_timeframe"]["trend_ema_donchian"]["1h"]
    assert fam_stats["median_cost_drag_pct"] == 40.0
    assert fam_stats["cost_drag_undefined_runs"] == 2
