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
