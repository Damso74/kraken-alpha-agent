"""Tournament CLI tests — synthetic cache only, no network."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_strategy_tournament import STRATEGIES, _load_candles
from src.bot.metrics import MAX_RISK_DENIAL_RATE
from src.bot.execution_simulator import ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.paper_engine import run_paper_backtest
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_manager import RiskManager
from tests.conftest_bot import synthetic_uptrend

REPO = Path(__file__).resolve().parents[1]


def test_tournament_backtest_on_synthetic_candles() -> None:
    candles = synthetic_uptrend(80)
    for _name, cls in STRATEGIES.items():
        result = run_paper_backtest(
            candles,
            cls(),
            PaperPortfolio(cash_usd=1000.0),
            RiskManager(),
            ExecutionSimulator(),
            BotJournal(),
            {"starting_equity": 1000.0},
            symbol="BTC",
            data_ok=True,
        )
        assert len(result.equity_curve) == len(candles)


def test_load_candles_missing_cache_returns_blocked() -> None:
    rows, ok = _load_candles("ZZZNOCACHE", min_rows=10)
    assert rows == []
    assert ok is False


def test_cli_help() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run_strategy_tournament.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0
    assert "--fees-bps" in proc.stdout


def test_tournament_writes_results(tmp_path: Path) -> None:
    out = tmp_path / "tournament"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_strategy_tournament.py"),
            "--assets",
            "BTC",
            "--output-dir",
            str(out),
            "--phase",
            "15",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0
    results_path = out / "results.json"
    assert results_path.is_file()
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["fee_bps"] == 40
    assert payload["slippage_bps"] == 5
    assert len(payload["runs"]) == 4
    run = payload["runs"][0]
    assert "risk_denials_count" in run
    assert "risk_denial_rate" in run
    assert "stopped_by_risk" in run
    assert MAX_RISK_DENIAL_RATE == 0.30
