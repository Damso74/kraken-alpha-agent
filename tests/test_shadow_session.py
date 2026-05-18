"""Tests for the shadow xStocks dry-run session: profile + exporter structure.

The shadow session itself can only be tested end-to-end with a real
agent loop, so these unit tests focus on the static guarantees:

- ``shadow_xstocks_36h`` profile loads with the expected hard-coded
  invariants (mode=dry_run, engine=spot, futures.enabled=false,
  caps within the documented envelope).
- ``scripts/export_shadow_session_for_submission.py`` produces a
  payload with the schema the submission UI reads, including the
  ``mode: "live_shadow_dry_run"`` flag.
- ``scripts/monitor_shadow_session.py`` parses the metadata file and
  renders without error against an empty / partial DB.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import config as cfg

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load_script(name: str):
    """Import a scripts/*.py module by its basename."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Profile invariants
# ---------------------------------------------------------------------------


def test_shadow_xstocks_36h_profile_loads_with_locked_invariants(monkeypatch) -> None:
    """The conftest pins CONFIG_PATH to config.example.yaml for isolation,
    so we override it here to point at the canonical config.yaml that
    declares the shadow profile.
    """
    monkeypatch.setenv("CONFIG_PATH", "config.yaml")
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "shadow_xstocks_36h")
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    try:
        assert s.active_profile == "shadow_xstocks_36h"
        assert s.config.trading.mode == "dry_run"
        assert s.config.execution.engine == "spot"
        # Futures must stay disabled on the shadow profile so the spot
        # engine path is the only one reachable.
        assert s.config.futures.enabled is False
        # Hard-cap envelope (matches docs/SHADOW_SESSION_INSTRUCTIONS.md).
        assert s.config.risk.max_total_exposure_usd == pytest.approx(100.0)
        assert s.config.risk.max_position_notional_usd == pytest.approx(25.0)
        assert s.config.risk.max_open_positions == 4
        # Cycle interval and dynamic top-N for liveliness.
        assert s.config.trading.cycle_interval_seconds == 60
        assert s.config.universe.top_n == 5
        # No-short invariant preserved.
        assert s.config.trading.shorting_enabled is False
        # Session guard active for BUY entries (xStocks core hours).
        assert "US_CORE" in s.config.trading.allowed_entry_sessions
    finally:
        cfg.get_settings.cache_clear()


def test_shadow_profile_universe_covers_top_xstocks(monkeypatch) -> None:
    monkeypatch.setenv("CONFIG_PATH", "config.yaml")
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "shadow_xstocks_36h")
    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    try:
        symbols = set(s.config.universe.symbols)
        # Spec requires at least the 9 symbols backtested in the
        # standard xStocks snapshot.
        required = {
            "AAPLx", "NVDAx", "TSLAx", "GOOGLx", "MSFTx",
            "AMZNx", "METAx", "MSTRx", "CRCLx",
        }
        missing = required - symbols
        assert not missing, f"shadow universe missing required xStocks: {missing}"
    finally:
        cfg.get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Exporter — structure of the produced JSON
# ---------------------------------------------------------------------------


def _make_test_db(tmp_path: Path, *, started_iso: str, ended_iso: str) -> Path:
    """Build a minimal agent.sqlite with two BUY/SELL pairs and one PnL snap."""
    db = tmp_path / "agent.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE cycles (
            id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT,
            duration_ms INTEGER, mode TEXT, symbols_seen INTEGER,
            decisions INTEGER, approved INTEGER, errors INTEGER,
            summary_json TEXT
        );
        CREATE TABLE decisions (
            id TEXT PRIMARY KEY, at TEXT, cycle_id TEXT, symbol TEXT,
            action TEXT, final_score REAL, confidence REAL,
            suggested_size_usd REAL, approved_size_usd REAL,
            regime TEXT, mode TEXT, approved INTEGER, rationale TEXT,
            payload_json TEXT
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, decision_id TEXT,
            mode TEXT, status TEXT, symbol TEXT, action TEXT,
            requested_size_usd REAL, filled_size_usd REAL, fill_price REAL,
            volume REAL, fee REAL, order_id TEXT, error TEXT, payload_json TEXT
        );
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY, quantity REAL, avg_entry_price REAL,
            market_price REAL, notional_usd REAL,
            unrealized_pnl_usd REAL, realized_pnl_usd REAL,
            updated_at TEXT, opened_at TEXT
        );
        CREATE TABLE pnl_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT,
            realized_usd REAL, unrealized_usd REAL, net_usd REAL,
            equity_usd REAL, drawdown_pct REAL, source TEXT,
            note TEXT, payload_json TEXT
        );
        CREATE TABLE errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT,
            where_label TEXT, message TEXT, context_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO cycles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "cyc1", started_iso, ended_iso, 5000, "dry_run",
            5, 5, 0, 0, '{"approved_actions":[]}',
        ),
    )
    # Two trade pairs on AAPLx — first wins (+0.5), second loses (-1.0).
    conn.execute(
        "INSERT INTO orders (at, mode, status, symbol, action, requested_size_usd, "
        "filled_size_usd, fill_price, volume, fee, order_id, error, payload_json) "
        "VALUES (?, 'dry_run', 'dry_run_logged', 'AAPLx', 'BUY', 25.0, 25.0, 100.0, 0.25, 0.025, 'dry_buy_1', NULL, '{}')",
        (started_iso,),
    )
    conn.execute(
        "INSERT INTO orders (at, mode, status, symbol, action, requested_size_usd, "
        "filled_size_usd, fill_price, volume, fee, order_id, error, payload_json) "
        "VALUES (?, 'dry_run', 'dry_run_logged', 'AAPLx', 'SELL', 25.0, 25.0, 102.0, 0.25, 0.025, 'dry_sell_1', NULL, '{}')",
        (ended_iso,),
    )
    conn.execute(
        "INSERT INTO orders (at, mode, status, symbol, action, requested_size_usd, "
        "filled_size_usd, fill_price, volume, fee, order_id, error, payload_json) "
        "VALUES (?, 'dry_run', 'dry_run_logged', 'NVDAx', 'BUY', 20.0, 20.0, 200.0, 0.10, 0.020, 'dry_buy_2', NULL, '{}')",
        (started_iso,),
    )
    conn.execute(
        "INSERT INTO orders (at, mode, status, symbol, action, requested_size_usd, "
        "filled_size_usd, fill_price, volume, fee, order_id, error, payload_json) "
        "VALUES (?, 'dry_run', 'dry_run_logged', 'NVDAx', 'SELL', 20.0, 20.0, 195.0, 0.10, 0.020, 'dry_sell_2', NULL, '{}')",
        (ended_iso,),
    )
    conn.execute(
        "INSERT INTO pnl_snapshots (at, realized_usd, unrealized_usd, net_usd, "
        "equity_usd, drawdown_pct, source, note, payload_json) "
        "VALUES (?, 0.5, 0.0, 0.5, 100.5, 0.0, 'test', '', '{}')",
        (ended_iso,),
    )
    conn.commit()
    conn.close()
    return db


def test_exporter_produces_valid_submission_schema(tmp_path: Path, monkeypatch) -> None:
    started = datetime(2026, 5, 18, 19, 0, 0, tzinfo=timezone.utc)
    ended = started + timedelta(hours=2)
    started_iso = started.isoformat().replace("+00:00", "Z")
    ended_iso = ended.isoformat().replace("+00:00", "Z")

    db = _make_test_db(tmp_path, started_iso=started_iso, ended_iso=ended_iso)
    metadata_path = tmp_path / "shadow_session.json"
    metadata_path.write_text(
        json.dumps({
            "started_at_utc": started_iso,
            "profile": "shadow_xstocks_36h",
            "loop_interval_s": 60,
            "log_file": str(tmp_path / "shadow_session.log"),
            "pid": 12345,
        }),
        encoding="utf-8",
    )
    out_path = tmp_path / "shadow_session_export.json"

    exporter = _load_script("export_shadow_session_for_submission")
    monkeypatch.setattr(
        sys, "argv",
        [
            "export_shadow_session_for_submission",
            "--db", str(db),
            "--metadata", str(metadata_path),
            "--until", ended_iso,
            "--out", str(out_path),
            "--starting-capital", "100",
            "--profile", "shadow_xstocks_36h",
        ],
    )
    rc = exporter.main()
    assert rc == 0
    assert out_path.exists()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    # Top-level invariants
    assert payload["mode"] == "live_shadow_dry_run"
    assert payload["engine"] == "dry_run"
    assert payload["profile"] == "shadow_xstocks_36h"
    assert payload["source"] == "live_shadow_session"
    # Session block
    sess = payload["session"]
    assert sess["started_at_utc"] == started_iso
    assert sess["ended_at_utc"] == ended_iso
    assert sess["cycles_dry_run"] == 1
    assert sess["loop_interval_s"] == 60
    # Summary block
    summ = payload["summary"]
    assert summ["total_trades"] == 2
    # Pair 1 (AAPLx): (102 - 100) * 0.25 = 0.5  -fees 0.05  -> 0.45
    # Pair 2 (NVDAx): (195 - 200) * 0.10 = -0.5 -fees 0.04 -> -0.54
    # Total = 0.45 - 0.54 = -0.09
    assert summ["winning_trades"] == 1
    assert summ["losing_trades"] == 1
    assert summ["total_pnl_usd"] == pytest.approx(-0.09, rel=0, abs=1e-3)
    # Trade list
    trades = payload["trades"]
    assert len(trades) == 2
    symbols = {t["symbol"] for t in trades}
    assert symbols == {"AAPLx", "NVDAx"}
    for t in trades:
        assert "pnl_usd" in t and "duration_min" in t
    # Equity curve has at least one point (from pnl_snapshots)
    assert len(payload["equity_curve"]) >= 1
    # Rejections / honest narrative still present
    assert "PEDSL-CY" in payload["rejections"]["account_class"]


# ---------------------------------------------------------------------------
# Monitor — render against the same fixture DB
# ---------------------------------------------------------------------------


def test_monitor_once_renders_against_test_db(tmp_path: Path, monkeypatch) -> None:
    started = datetime(2026, 5, 18, 19, 0, 0, tzinfo=timezone.utc)
    ended = started + timedelta(hours=2)
    started_iso = started.isoformat().replace("+00:00", "Z")
    ended_iso = ended.isoformat().replace("+00:00", "Z")

    db = _make_test_db(tmp_path, started_iso=started_iso, ended_iso=ended_iso)
    metadata_path = tmp_path / "shadow_session.json"
    metadata_path.write_text(
        json.dumps({
            "started_at_utc": started_iso,
            "profile": "shadow_xstocks_36h",
            "loop_interval_s": 60,
            "log_file": str(tmp_path / "shadow_session.log"),
            "pid": 12345,
        }),
        encoding="utf-8",
    )

    monitor = _load_script("monitor_shadow_session")
    state = monitor.SessionState(
        started_at_utc=started,
        cutoff_at_utc=ended + timedelta(hours=10),
        db_path=db,
        log_path=tmp_path / "shadow_session.log",
        metadata=json.loads(metadata_path.read_text(encoding="utf-8")),
    )
    rendered = monitor._render(state)
    assert "SHADOW XSTOCKS DRY-RUN MONITOR" in rendered
    assert "started_at" in rendered
    assert "Cycles since session start" in rendered
    # The fixture DB has 2 dry_run pairs → 4 orders total
    assert "trades_total: 4" in rendered or "trades_total: 4 " in rendered
    # Universe seen falls back to distinct decision symbols (none here),
    # so no AAPLx/NVDAx claim is asserted on the universe line — the
    # important thing is the renderer does not raise.


def test_monitor_metadata_fallback_when_no_file(tmp_path: Path, monkeypatch) -> None:
    """When no shadow_session.json exists and no --since is set, the monitor
    must still render (using "now" as the start) without raising.
    """
    db = tmp_path / "agent.sqlite"
    # Empty DB with the expected schema.
    sqlite3.connect(str(db)).executescript(
        "CREATE TABLE cycles (id TEXT, started_at TEXT, finished_at TEXT, "
        "duration_ms INTEGER, mode TEXT, symbols_seen INTEGER, decisions INTEGER, "
        "approved INTEGER, errors INTEGER, summary_json TEXT);"
        "CREATE TABLE decisions (id TEXT, at TEXT, cycle_id TEXT, symbol TEXT, "
        "action TEXT, final_score REAL, confidence REAL, suggested_size_usd REAL, "
        "approved_size_usd REAL, regime TEXT, mode TEXT, approved INTEGER, "
        "rationale TEXT, payload_json TEXT);"
        "CREATE TABLE orders (id INTEGER, at TEXT, decision_id TEXT, mode TEXT, "
        "status TEXT, symbol TEXT, action TEXT, requested_size_usd REAL, "
        "filled_size_usd REAL, fill_price REAL, volume REAL, fee REAL, "
        "order_id TEXT, error TEXT, payload_json TEXT);"
        "CREATE TABLE positions (symbol TEXT, quantity REAL, avg_entry_price REAL, "
        "market_price REAL, notional_usd REAL, unrealized_pnl_usd REAL, "
        "realized_pnl_usd REAL, updated_at TEXT, opened_at TEXT);"
        "CREATE TABLE pnl_snapshots (id INTEGER, at TEXT, realized_usd REAL, "
        "unrealized_usd REAL, net_usd REAL, equity_usd REAL, drawdown_pct REAL, "
        "source TEXT, note TEXT, payload_json TEXT);"
        "CREATE TABLE errors (id INTEGER, at TEXT, where_label TEXT, message TEXT, "
        "context_json TEXT);"
    )

    monitor = _load_script("monitor_shadow_session")
    state = monitor.SessionState(
        started_at_utc=datetime.now(timezone.utc),
        cutoff_at_utc=datetime.now(timezone.utc) + timedelta(hours=24),
        db_path=db,
        log_path=tmp_path / "shadow_session.log",
        metadata={},
    )
    rendered = monitor._render(state)
    assert "trades_total: 0" in rendered
    assert "Open simulated positions" in rendered
