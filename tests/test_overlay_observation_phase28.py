"""Phase 28 — overlay observation daemon tests (no network, no live)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.bot.overlay_observation_engine import ObservationConfig, run_observation_once
from src.bot.overlay_observation_kill import (
    OverlayKillConfig,
    evaluate_overlay_kill,
    observation_stop_active,
    write_observation_stop,
)

REPO = Path(__file__).resolve().parents[1]


def _write_eth4h_cache(cache: Path, n: int = 120) -> None:
    t0 = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp())
    step = 14400
    candles = [
        {
            "timestamp": t0 + i * step,
            "open": 2000.0 + i * 2,
            "high": 2010.0 + i * 2,
            "low": 1990.0 + i * 2,
            "close": 2005.0 + i * 2,
            "volume": 100.0,
        }
        for i in range(n)
    ]
    cache.mkdir(parents=True, exist_ok=True)
    payload = {"interval_minutes": 240, "entries": {"candles": candles}}
    (cache / "ohlc_4h_ETH.json").write_text(json.dumps(payload), encoding="utf-8")

    fund = [
        {"timestamp": t0 + i * step, "funding_rate": 0.0001 + (i % 10) * 0.00001}
        for i in range(0, n, 2)
    ]
    (cache / "funding_ETH.json").write_text(
        json.dumps({"entries": {"rows": fund}, "status": "available"}),
        encoding="utf-8",
    )
    basis = [
        {
            "timestamp": t0 + i * step,
            "spot_price": 2000.0,
            "perp_price": 2002.0,
            "basis_pct": 0.001,
            "basis_zscore": 0.3 + (i % 5) * 0.1,
            "basis_compression": False,
            "basis_extreme": False,
        }
        for i in range(0, n, 2)
    ]
    (cache / "basis_ETH_4h.json").write_text(
        json.dumps({"entries": {"rows": basis}, "status": "available"}),
        encoding="utf-8",
    )


def test_observation_once_creates_state(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_eth4h_cache(cache)
    state = tmp_path / "state"
    cfg = ObservationConfig(
        asset="ETH",
        timeframe="4h",
        strategy="trend_following",
        variant="baseline",
        overlay="funding_basis",
        state_dir=state,
        cache_root=cache,
        observation_only=True,
    )
    out = run_observation_once(cfg)
    assert out["status"] == "ok"
    assert out["observation_only"] is True
    assert (state / "state.json").is_file()
    assert (state / "decisions.jsonl").is_file()
    assert (state / "shadow_comparison.jsonl").is_file()
    assert (state / "equity_curve.csv").is_file()


def test_observation_once_idempotent_skip(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_eth4h_cache(cache)
    state = tmp_path / "state"
    cfg = ObservationConfig(state_dir=state, cache_root=cache)
    first = run_observation_once(cfg)
    second = run_observation_once(cfg)
    assert first["status"] == "ok"
    assert second["status"] == "skipped"
    assert second["reason"] == "duplicate_candle"


def test_kill_criteria_stop_file(tmp_path: Path) -> None:
    stop = tmp_path / "STOP_OBSERVATION"
    write_observation_stop(stop, "test kill")
    assert observation_stop_active(stop)
    result = evaluate_overlay_kill(tmp_path, stop_file=stop)
    assert result.should_kill
    assert "stop_file_active" in result.reasons


def test_kill_block_rate(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow_comparison.jsonl"
    rows = []
    for i in range(10):
        rows.append(
            {
                "overlay_blocks": True,
                "standalone_would_trade": True,
                "overlay_decision": "block",
                "funding_z": 2.5,
                "basis_z": 2.5,
            }
        )
    shadow.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    result = evaluate_overlay_kill(
        tmp_path,
        config=OverlayKillConfig(max_block_rate=0.5, min_trades_for_judgment=3),
        trade_count=10,
    )
    assert result.should_kill
    assert any("overlay_blocks_too_often" in r for r in result.reasons)


def test_daemon_cli_once(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_eth4h_cache(cache)
    state = tmp_path / "state"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_overlay_observation_daemon_phase28.py"),
            "--asset",
            "ETH",
            "--timeframe",
            "4h",
            "--strategy",
            "ema_crossover",
            "--variant",
            "baseline",
            "--overlay",
            "funding_basis",
            "--state-dir",
            str(state),
            "--cache-root",
            str(cache),
            "--mode",
            "once",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["observation_only"] is True


def test_no_live_imports_in_daemon_script() -> None:
    text = (REPO / "scripts" / "run_overlay_observation_daemon_phase28.py").read_text(
        encoding="utf-8"
    )
    assert "execution.py" not in text
    assert "futures_kraken_cli" not in text
    assert "ALLOW_LIVE_ORDERS" not in text
    assert "run_agent_loop" not in text
