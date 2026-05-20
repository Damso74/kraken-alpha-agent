"""Phase 24 data backbone audit — hermetic tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.bot.phase24_data_backbone import (
    PHASE24_MIN_BARS,
    PHASE24_REQUIRED_ASSETS,
    PHASE23_FACTORY_MAX_BARS,
    audit_cache_entry,
    build_inventory,
    discover_cached_assets,
    summarize_inventory,
)
from src.data.collectors.binance_public import default_ohlc_cache_path, save_ohlc_cache

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable


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


def _seed_phase24_cache(tmp_path: Path, asset: str = "BTC") -> Path:
    cache_root = tmp_path / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    for tf, step in (("1d", 86400), ("4h", 14400)):
        rows = _make_candles(count=PHASE24_MIN_BARS[tf] + 50, step_seconds=step)
        path = cache_root / default_ohlc_cache_path(asset, tf).name
        save_ohlc_cache(path, ticker=asset, timeframe=tf, rows=rows)
    extra = cache_root / default_ohlc_cache_path("XRP", "1d").name
    save_ohlc_cache(
        extra,
        ticker="XRP",
        timeframe="1d",
        rows=_make_candles(count=PHASE24_MIN_BARS["1d"] + 10, step_seconds=86400),
    )
    return cache_root


def test_discover_cached_assets_includes_watchlist(tmp_path: Path) -> None:
    cache = _seed_phase24_cache(tmp_path)
    assets = discover_cached_assets(cache)
    assert "BTC" in assets
    assert "XRP" in assets


def test_audit_data_ok_and_phase23_delta(tmp_path: Path) -> None:
    cache = _seed_phase24_cache(tmp_path)
    row = audit_cache_entry("BTC", "1d", cache)
    assert row["data_ok"] is True
    assert row["bar_count"] >= PHASE24_MIN_BARS["1d"]
    assert row["delta_bars_vs_phase23_cap"] == max(
        0, row["bar_count"] - PHASE23_FACTORY_MAX_BARS
    )


def test_build_inventory_required_complete(tmp_path: Path) -> None:
    cache = _seed_phase24_cache(tmp_path)
    for asset in PHASE24_REQUIRED_ASSETS:
        for tf in ("1d", "4h"):
            rows = _make_candles(
                count=PHASE24_MIN_BARS[tf] + 30,
                step_seconds=86400 if tf == "1d" else 14400,
            )
            path = cache / default_ohlc_cache_path(asset, tf).name
            save_ohlc_cache(path, ticker=asset, timeframe=tf, rows=rows)
    entries = build_inventory(cache)
    summary = summarize_inventory(entries)
    assert summary["required_complete"] is True


def test_audit_script_fast(tmp_path: Path) -> None:
    cache = _seed_phase24_cache(tmp_path)
    out = tmp_path / "reports"
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "audit_data_backbone_phase24.py"),
            "--cache-root",
            str(cache),
            "--report-dir",
            str(out),
            "--assets",
            "BTC",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (out / "data_quality.json").is_file()
    payload = json.loads((out / "data_quality.json").read_text(encoding="utf-8"))
    assert payload["phase"] == 24


@pytest.mark.parametrize(
    "script",
    (
        "audit_data_backbone_phase24.py",
        "run_lowfreq_walkforward_sensitivity_phase24.py",
        "generate_phase24_reports.py",
    ),
)
def test_phase24_script_help(script: str) -> None:
    proc = subprocess.run(
        [PY, str(REPO / "scripts" / script), "--help"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
