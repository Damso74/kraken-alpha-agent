"""Pytest fixtures.

We make sure every test run uses an isolated SQLite + JSONL workspace by
overriding the relevant environment variables before any project module is
imported.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "agent.sqlite"))
    monkeypatch.setenv("DECISIONS_LOG_PATH", str(tmp_path / "decisions.jsonl"))
    monkeypatch.setenv("TRADES_LOG_PATH", str(tmp_path / "trades.jsonl"))
    monkeypatch.setenv("PNL_LOG_PATH", str(tmp_path / "pnl.jsonl"))
    monkeypatch.setenv("CONFIG_PATH", "config.example.yaml")
    monkeypatch.setenv("TRADING_MODE", "dry_run")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "false")
    monkeypatch.setenv("KRAKEN_API_KEY", "")
    monkeypatch.setenv("KRAKEN_API_SECRET", "")
    monkeypatch.setenv("FEATHERLESS_API_KEY", "")

    # Drop any cached Settings so the new env values take effect.
    from src import config as cfg

    cfg.get_settings.cache_clear()
    from src import risk as risk_mod

    risk_mod.reset_cooldowns()
    yield
    cfg.get_settings.cache_clear()
    risk_mod.reset_cooldowns()
