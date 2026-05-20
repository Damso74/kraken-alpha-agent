"""Integration tests for walk-forward tournament runner (Phase 17)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _write_synthetic_cache(cache: Path, asset: str, interval: int, n: int, step: int) -> None:
    candles = []
    for i in range(n):
        candles.append(
            {
                "timestamp": 1_700_000_000 + i * step,
                "open": 100.0 + i * 0.1,
                "high": 101.0 + i * 0.1,
                "low": 99.0 + i * 0.1,
                "close": 100.0 + i * 0.1,
                "volume": 1.0,
            }
        )
    cache.mkdir(parents=True, exist_ok=True)
    if interval == 1440:
        fname = f"ohlc_daily_{asset}.json"
    elif interval == 240:
        fname = f"ohlc_4h_{asset}.json"
    else:
        fname = f"ohlc_1h_{asset}.json"
    payload = {"interval_minutes": interval, "entries": {"candles": candles}}
    (cache / fname).write_text(json.dumps(payload), encoding="utf-8")


def test_walkforward_tournament_insufficient_candles(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_synthetic_cache(cache, "ZZ", 1440, 120, 86400)
    out = tmp_path / "wf"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_walkforward_tournament.py"),
            "--assets",
            "ZZ",
            "--timeframes",
            "1d",
            "--strategies",
            "ema_crossover",
            "--output-dir",
            str(out),
            "--cache-root",
            str(cache),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert payload["phase"] == 17
    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["verdict"] == "insufficient_candles"


def test_walkforward_tournament_blocked_data(tmp_path: Path) -> None:
    cache = tmp_path / "empty_cache"
    cache.mkdir()
    out = tmp_path / "wf_blocked"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_walkforward_tournament.py"),
            "--assets",
            "NOPE",
            "--timeframes",
            "1d",
            "--strategies",
            "grid",
            "--output-dir",
            str(out),
            "--cache-root",
            str(cache),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert payload["runs"][0]["verdict"] == "blocked_data"


def test_walkforward_tournament_enough_candles(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_synthetic_cache(cache, "WF", 1440, 600, 86400)
    out = tmp_path / "wf_ok"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_walkforward_tournament.py"),
            "--assets",
            "WF",
            "--timeframes",
            "1d",
            "--strategies",
            "trend_following",
            "--output-dir",
            str(out),
            "--cache-root",
            str(cache),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert payload["runs"][0]["windows_total"] >= 1
    assert (out / "window_results.csv").is_file()
