"""Phase 23 low-freq factory — hermetic tests (no network)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts._phase23_common import apply_overlay, build_phase23_instrument
from src.bot.phase23_presets import (
    PHASE23_LOWFREQ_STRATEGIES,
    PHASE23_VARIANTS,
    get_phase23_params,
    list_phase23_combos,
)
from src.bot.phase23_walkforward import classify_phase23_walkforward_verdict
from src.bot.regime_overlay import RegimeOverlayStrategy
from src.bot.walkforward_metrics import WindowRunMetrics, aggregate_window_metrics
from src.data.collectors.binance_public import (
    MIN_ROWS_DATA_OK,
    default_ohlc_cache_path,
    save_ohlc_cache,
)

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable

SCRIPTS = (
    "run_lowfreq_candidate_factory_phase23.py",
    "run_lowfreq_walkforward_phase23.py",
    "run_regime_overlay_phase23.py",
    "generate_phase23_reports.py",
)


def _make_candles(*, count: int, step_seconds: int) -> list[dict]:
    start_ts = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    out: list[dict] = []
    for i in range(count):
        ts = start_ts + i * step_seconds
        close = 50_000.0 + i * 0.5
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
    for tf, step in (("1d", 86400), ("4h", 14400)):
        rows = _make_candles(count=MIN_ROWS_DATA_OK[tf] + 40, step_seconds=step)
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
    assert "usage:" in proc.stdout.lower() or "Phase 23" in proc.stdout


def test_phase23_preset_grid_locked() -> None:
    assert len(PHASE23_LOWFREQ_STRATEGIES) == 4
    assert len(PHASE23_VARIANTS) == 3
    base = get_phase23_params("ema_crossover", "1d", "baseline")
    slow = get_phase23_params("ema_crossover", "1d", "slow")
    assert slow["fast_period"] > base["fast_period"]
    assert len(list_phase23_combos()) == 4 * 3 * 3 * 2


def test_regime_overlay_wraps_inner() -> None:
    inner = build_phase23_instrument("donchian_breakout", "4h", "baseline", "off")
    wrapped = apply_overlay(inner, "4h", "panic")
    assert isinstance(wrapped, RegimeOverlayStrategy)


def test_factory_fast_run(tmp_path: Path) -> None:
    cache = _seed_cache(tmp_path)
    out = tmp_path / "factory"
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "run_lowfreq_candidate_factory_phase23.py"),
            "--fast",
            "--output-dir",
            str(out),
            "--cache-root",
            str(cache),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert payload["phase"] == 23
    assert len(payload["runs"]) == 1
    assert (out / "results_matrix.csv").is_file()


def test_walkforward_fast_run(tmp_path: Path) -> None:
    cache = _seed_cache(tmp_path)
    out = tmp_path / "wf"
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "run_lowfreq_walkforward_phase23.py"),
            "--fast",
            "--output-dir",
            str(out),
            "--cache-root",
            str(cache),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert payload["phase"] == 23
    assert len(payload["runs"]) >= 1
    for run in payload["runs"]:
        assert run.get("verdict") != "paper_candidate"


def test_phase23_wf_bh_gate_downgrades() -> None:
    runs = [
        WindowRunMetrics(i, "holdout", 3.0 + i, 8.0, trade_count=10)
        for i in range(5)
    ]
    agg = aggregate_window_metrics(runs)
    v = classify_phase23_walkforward_verdict(
        agg,
        {
            "data_ok": True,
            "bh_max_drawdown_pct": 5.0,
            "full_max_drawdown_pct": 20.0,
            "total_trade_count": 50,
            "turnover_ratio": 1.0,
            "asset_returns": {"BTC": 1.0, "ETH": 0.5},
        },
    )
    assert v.verdict == "validation_candidate"
