"""Integration tests for paper daemon (Phase 19)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _write_cache(cache: Path, asset: str, n: int) -> None:
    candles = [
        {
            "timestamp": 1_700_000_000 + i * 86400,
            "open": 100.0 + i * 0.1,
            "high": 101.0 + i * 0.1,
            "low": 99.0 + i * 0.1,
            "close": 100.0 + i * 0.1,
            "volume": 1.0,
        }
        for i in range(n)
    ]
    cache.mkdir(parents=True, exist_ok=True)
    payload = {"interval_minutes": 1440, "entries": {"candles": candles}}
    (cache / f"ohlc_daily_{asset}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_paper_daemon_once(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_cache(cache, "PD", 80)
    state = tmp_path / "state"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_paper_daemon.py"),
            "--asset",
            "PD",
            "--timeframe",
            "1d",
            "--strategy",
            "trend_following",
            "--state-dir",
            str(state),
            "--cache-root",
            str(cache),
            "--mode",
            "once",
            "--observation-only",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert (state / "state.json").is_file()


def test_generate_daily_report_cli(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "state.json").write_text(
        json.dumps({"equity": 1000.0, "mode": "observation"}), encoding="utf-8"
    )
    out = tmp_path / "live"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "generate_paper_daily_report.py"),
            "--state-dir",
            str(state),
            "--output-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert any(out.glob("daily_summary_*.md"))
