"""Phase 25 candidate autopsy — hermetic unit tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.bot.phase23_presets import get_phase23_params
from src.bot.phase25_autopsy import (
    AutopsyTestResult,
    BacktestSnapshot,
    CandidateSpec,
    build_trend_following_instrument,
    check_drawdown_acceptability,
    check_trade_concentration,
    classify_final_verdict,
    extract_round_trip_pnls,
    run_full_autopsy,
)
from src.data.collectors.binance_public import (
    MIN_ROWS_DATA_OK,
    default_ohlc_cache_path,
    save_ohlc_cache,
)

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable


def _make_candles(*, count: int, step_seconds: int, start_year: int = 2020) -> list[dict]:
    start_ts = int(datetime(start_year, 1, 1, tzinfo=UTC).timestamp())
    return [
        {
            "timestamp": start_ts + i * step_seconds,
            "open": 100.0 + i * 0.01,
            "high": 101.0 + i * 0.01,
            "low": 99.0 + i * 0.01,
            "close": 100.0 + i * 0.01,
            "vwap": 100.0 + i * 0.01,
            "volume": 1.0,
        }
        for i in range(count)
    ]


def _seed_eth_4h_cache(tmp_path: Path) -> Path:
    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    n = MIN_ROWS_DATA_OK["4h"] + 200
    rows = _make_candles(count=n, step_seconds=14400, start_year=2021)
    path = cache_root / default_ohlc_cache_path("ETH", "4h").name
    save_ohlc_cache(path, ticker="ETH", timeframe="4h", rows=rows)
    for asset in ("BTC", "SOL"):
        p = cache_root / default_ohlc_cache_path(asset, "4h").name
        save_ohlc_cache(
            p,
            ticker=asset,
            timeframe="4h",
            rows=_make_candles(count=n, step_seconds=14400),
        )
    p1d = cache_root / default_ohlc_cache_path("ETH", "1d").name
    save_ohlc_cache(
        p1d,
        ticker="ETH",
        timeframe="1d",
        rows=_make_candles(count=MIN_ROWS_DATA_OK["1d"] + 100, step_seconds=86400),
    )
    return cache_root


def test_slow_variant_scales_periods() -> None:
    base = get_phase23_params("trend_following", "4h", "baseline")
    slow = get_phase23_params("trend_following", "4h", "slow")
    assert slow["fast_period"] > base["fast_period"]
    assert slow["slow_period"] > base["slow_period"]


def test_build_trend_following_custom_mult() -> None:
    inst = build_trend_following_instrument("4h", "slow", fast_mult=0.9, slow_mult=1.1)
    slow = get_phase23_params("trend_following", "4h", "slow")
    assert inst.fast_period == max(2, int(round(slow["fast_period"] * 0.9)))
    assert inst.slow_period == max(2, int(round(slow["slow_period"] * 1.1)))


def test_extract_round_trip_pnls() -> None:
    from src.bot.journal import BotJournal

    j = BotJournal()
    j.trades = [
        {"side": "buy", "price": 100.0, "quantity": 1.0, "fee_usd": 0.1},
        {"side": "sell", "price": 110.0, "quantity": 1.0, "fee_usd": 0.1},
        {"side": "buy", "price": 200.0, "quantity": 0.5, "fee_usd": 0.0},
        {"side": "sell", "price": 180.0, "quantity": 0.5, "fee_usd": 0.0},
    ]
    pnls = extract_round_trip_pnls(j)
    assert len(pnls) == 2
    assert pnls[0] > 0
    assert pnls[1] < 0


def test_classify_final_verdict_kill_on_fail() -> None:
    tests = [
        AutopsyTestResult("reproducibility", "fail", ""),
        AutopsyTestResult("param_sensitivity", "pass", ""),
        AutopsyTestResult("fee_sensitivity", "pass", ""),
        AutopsyTestResult("period_splits", "pass", ""),
        AutopsyTestResult("trade_concentration", "pass", ""),
        AutopsyTestResult("drawdown_acceptability", "pass", ""),
        AutopsyTestResult("asset_placebo", "warn", ""),
    ]
    assert classify_final_verdict(tests) == "kill"


def test_classify_final_verdict_weak_on_placebo_warn() -> None:
    tests = [
        AutopsyTestResult("reproducibility", "pass", ""),
        AutopsyTestResult("param_sensitivity", "pass", ""),
        AutopsyTestResult("fee_sensitivity", "pass", ""),
        AutopsyTestResult("period_splits", "pass", ""),
        AutopsyTestResult("trade_concentration", "pass", ""),
        AutopsyTestResult("drawdown_acceptability", "pass", ""),
        AutopsyTestResult("asset_placebo", "warn", ""),
    ]
    assert classify_final_verdict(tests) == "weak"


def test_trade_concentration_kill_threshold() -> None:
    snap = BacktestSnapshot(
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        trade_pnls=[100.0, 1.0, 1.0],
    )
    r = check_trade_concentration(snap)
    assert r.verdict == "fail"


def test_drawdown_acceptability_requires_5pp() -> None:
    snap = BacktestSnapshot(
        5.0,
        4.0,
        1.0,
        25.0,
        27.0,
        10,
        0.0,
        0.0,
        40.0,
        5.0,
        drawdown_reduction_vs_bh=2.0,
        calmar_like=0.2,
        bh_calmar_like=0.15,
    )
    assert check_drawdown_acceptability(snap).verdict == "fail"


def test_run_full_autopsy_hermetic(tmp_path: Path) -> None:
    cache = _seed_eth_4h_cache(tmp_path)
    payload = run_full_autopsy(CandidateSpec(), cache_root=cache)
    assert payload["phase"] == 25
    assert payload["final_verdict"] in ("kill", "weak", "paper_observation_candidate")
    assert payload["paper_candidate_count"] == 0
    assert len(payload["tests"]) == 7


def test_autopsy_script_fast(tmp_path: Path) -> None:
    cache = _seed_eth_4h_cache(tmp_path)
    out = tmp_path / "out"
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "run_candidate_autopsy_phase25.py"),
            "--output-dir",
            str(out),
            "--cache-root",
            str(cache),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["phase"] == 25
