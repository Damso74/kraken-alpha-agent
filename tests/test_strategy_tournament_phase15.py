"""Phase 15 tournament CLI tests — synthetic cache only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.run_strategy_tournament import STRATEGIES, _load_candles, _strategy_names
from src.bot.metrics import MIN_TRADES_BY_TIMEFRAME
from src.bot.portfolio import PaperPortfolio
from src.strategies.presets import build_strategy
from tests.conftest_bot import synthetic_uptrend

REPO = Path(__file__).resolve().parents[1]


def test_multi_timeframe_help() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run_strategy_tournament.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0
    assert "--timeframes" in proc.stdout
    assert "--cache-only" in proc.stdout


def test_tournament_writes_matrix(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    candles = []
    for i in range(80):
        candles.append(
            {
                "timestamp": 1_700_000_000 + i * 86400,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1.0,
            }
        )
    cache.mkdir()
    payload = {"interval_minutes": 1440, "entries": {"candles": candles}}
    (cache / "ohlc_daily_XX.json").write_text(json.dumps(payload), encoding="utf-8")

    out = tmp_path / "tournament"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_strategy_tournament.py"),
            "--assets",
            "XX",
            "--timeframes",
            "1d",
            "--output-dir",
            str(out),
            "--cache-root",
            str(cache),
            "--phase",
            "15",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0
    assert (out / "results_matrix.csv").is_file()
    payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert payload["phase"] == 15
    assert len(payload["runs"]) == 4


def test_preset_build_on_synthetic() -> None:
    """Le preset doit etre construit ET exploitable sur des bougies synthetiques.

    ``candles`` etait construit puis jamais utilise : le test ne verifiait que
    ``warmup_bars()``, donc rien de ce que son nom annonce. On fait maintenant
    tourner la strategie sur la serie haussiere : avant le warm-up elle doit
    rester en ``hold``, apres elle doit emettre un ``buy`` (SMA rapide > lente).
    """
    candles = synthetic_uptrend(120)
    strat = build_strategy("trend_following", "1d")
    assert strat.warmup_bars() == 51

    portfolio = PaperPortfolio(cash_usd=1000.0)
    warming = strat.on_bar(10, candles, portfolio, "XX")
    assert warming is not None and warming.action == "hold"

    signal = strat.on_bar(len(candles) - 1, candles, portfolio, "XX")
    assert signal is not None and signal.action == "buy"
    assert 0.0 < signal.size_fraction <= 1.0


def test_min_trades_by_timeframe() -> None:
    assert MIN_TRADES_BY_TIMEFRAME["1h"] == 20


def test_load_candles_missing() -> None:
    rows, ok = _load_candles("ZZZNOCACHE", min_rows=10)
    assert rows == []
    assert ok is False


def test_strategies_registry() -> None:
    assert set(_strategy_names(15)) == {
        "trend_following",
        "breakout",
        "mean_reversion",
        "grid",
    }
    assert len(STRATEGIES) == 9
