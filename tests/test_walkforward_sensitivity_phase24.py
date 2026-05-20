"""Phase 24 walk-forward holdout sensitivity — hermetic tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.bot.phase24_walkforward import (
    HOLDOUT_PCT_VARIANTS,
    PHASE24_PAPER_CANDIDATE_FORBIDDEN,
    classify_phase24_sensitivity_verdict,
    count_holdout_beats_bh,
    create_holdout_sensitivity_plan,
    scaled_holdout_bars,
)
from src.bot.walkforward_metrics import WindowRunMetrics, aggregate_window_metrics
from src.data.collectors.binance_public import (
    MIN_ROWS_DATA_OK,
    default_ohlc_cache_path,
    save_ohlc_cache,
)

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable


def _make_candles(*, count: int, step_seconds: int) -> list[dict]:
    start_ts = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    return [
        {
            "timestamp": start_ts + i * step_seconds,
            "open": 100.0 + i,
            "high": 101.0 + i,
            "low": 99.0 + i,
            "close": 100.5 + i,
            "vwap": 100.5 + i,
            "volume": 1.0,
        }
        for i in range(count)
    ]


def _seed_wf_cache(tmp_path: Path) -> Path:
    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    for tf, step in (("1d", 86400), ("4h", 14400)):
        rows = _make_candles(count=MIN_ROWS_DATA_OK[tf] + 80, step_seconds=step)
        path = cache_root / default_ohlc_cache_path("BTC", tf).name
        save_ohlc_cache(path, ticker="BTC", timeframe=tf, rows=rows)
    return cache_root


def test_scaled_holdout_bars_increase_with_pct() -> None:
    h20 = scaled_holdout_bars("1d", 0.20)
    h40 = scaled_holdout_bars("1d", 0.40)
    assert h40 > h20


def test_create_holdout_sensitivity_rolling_and_expanding() -> None:
    candles = _make_candles(count=800, step_seconds=86400)
    for pct in HOLDOUT_PCT_VARIANTS:
        rolling = create_holdout_sensitivity_plan(
            candles, "1d", pct, window_mode="rolling"
        )
        expanding = create_holdout_sensitivity_plan(
            candles, "1d", pct, window_mode="expanding"
        )
        assert rolling.status == "ok"
        assert len(rolling.windows) >= 1
        assert expanding.status == "ok"
        assert len(expanding.windows) == 1


def test_paper_candidate_forbidden_flag() -> None:
    assert PHASE24_PAPER_CANDIDATE_FORBIDDEN is True


def test_classify_never_returns_paper_candidate_walkforward() -> None:
    runs = [
        WindowRunMetrics(i, "holdout", 5.0 + i, 5.0, trade_count=20)
        for i in range(5)
    ]
    agg = aggregate_window_metrics(runs)
    v = classify_phase24_sensitivity_verdict(
        agg,
        {
            "data_ok": True,
            "holdout_beats_bh_count": 5,
            "holdout_bh_windows": 5,
            "total_trade_count": 100,
            "bh_max_drawdown_pct": 30.0,
            "full_max_drawdown_pct": 5.0,
            "median_excess_vs_bh_pct": 2.0,
            "full_excess_vs_bh_pct": 1.0,
        },
    )
    assert v.verdict != "paper_candidate_walkforward"
    assert v.verdict != "paper_candidate"


def test_full_excess_gate_blocks_validation() -> None:
    runs = [
        WindowRunMetrics(i, "holdout", 2.0, 5.0, trade_count=20)
        for i in range(5)
    ]
    agg = aggregate_window_metrics(runs)
    v = classify_phase24_sensitivity_verdict(
        agg,
        {
            "data_ok": True,
            "holdout_beats_bh_count": 5,
            "holdout_bh_windows": 5,
            "total_trade_count": 100,
            "bh_max_drawdown_pct": 30.0,
            "full_max_drawdown_pct": 5.0,
            "median_excess_vs_bh_pct": 2.0,
            "full_excess_vs_bh_pct": -5.0,
        },
    )
    assert v.verdict != "validation_candidate"


def test_count_holdout_beats_bh() -> None:
    runs = [
        WindowRunMetrics(0, "holdout", 3.0, 5.0, trade_count=2),
        WindowRunMetrics(1, "holdout", -1.0, 5.0, trade_count=2),
        WindowRunMetrics(2, "holdout", 2.0, 5.0, trade_count=2),
    ]
    beats, med = count_holdout_beats_bh(runs, [1.0, 0.0, 1.5])
    assert beats == 2
    assert med != 0.0


def test_wf_sensitivity_fast_run(tmp_path: Path) -> None:
    cache = _seed_wf_cache(tmp_path)
    out = tmp_path / "wf"
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "run_lowfreq_walkforward_sensitivity_phase24.py"),
            "--fast",
            "--output-dir",
            str(out),
            "--cache-root",
            str(cache),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["phase"] == 24
    assert summary["paper_candidate_count"] == 0
    assert (out / "results.csv").is_file()
