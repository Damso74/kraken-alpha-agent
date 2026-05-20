"""Integration tests for regime router tournament (Phase 18)."""

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
            "open": 100.0 + i * 0.2,
            "high": 101.0 + i * 0.2,
            "low": 99.0 + i * 0.2,
            "close": 100.0 + i * 0.2,
            "volume": 10.0,
        }
        for i in range(n)
    ]
    cache.mkdir(parents=True, exist_ok=True)
    payload = {"interval_minutes": 1440, "entries": {"candles": candles}}
    (cache / f"ohlc_daily_{asset}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_regime_router_tournament(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_cache(cache, "RR", 120)
    out = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_regime_router_tournament.py"),
            "--assets",
            "RR",
            "--timeframes",
            "1d",
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
    assert payload["phase"] == 18
    assert len(payload["runs"]) == 4
    assert (out / "equity_curve.csv").is_file()
