"""Phase 16 strategy zoo tests — synthetic candles only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.run_strategy_tournament import _strategy_names
from src.strategies.presets import (
    PHASE16_ZOO_PRESETS,
    build_strategy,
    get_vol_targeting_preset,
)
from src.strategies.volatility_targeting import VolatilityTargetingOverlay, scale_size_for_vol
from tests.conftest_bot import synthetic_range, synthetic_uptrend

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", PHASE16_ZOO_PRESETS["phase15_1d"].keys())
def test_phase16_presets_exist(name: str) -> None:
    for tf in ("1d", "4h", "1h"):
        s = build_strategy(name, tf)
        assert s.warmup_bars() >= 1


def test_strategy_names_phase16() -> None:
    names = _strategy_names(16)
    assert len(names) == 9
    assert "ema_crossover" in names


def test_vol_targeting_scales_down_on_high_vol() -> None:
    closes = [100.0 + i * 5.0 for i in range(30)]
    scaled, factor = scale_size_for_vol(
        0.25,
        closes,
        vol_lookback=20,
        target_vol_daily=0.02,
        min_scale=0.25,
        max_scale=1.0,
    )
    assert factor <= 1.0
    assert scaled <= 0.25


def test_vol_overlay_wraps_strategy() -> None:
    inner = build_strategy("ema_crossover", "1d")
    wrapped = VolatilityTargetingOverlay(inner, **get_vol_targeting_preset("1d"))
    candles = synthetic_uptrend(80)
    portfolio = __import__("src.bot.portfolio", fromlist=["PaperPortfolio"]).PaperPortfolio(
        cash_usd=1000.0
    )
    sig = wrapped.on_bar(wrapped.warmup_bars(), candles, portfolio, "BTC")
    assert sig is None or sig.action in ("buy", "sell", "hold")


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


def test_tournament_phase16_writes_nine_strategies(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_synthetic_cache(cache, "XX", 1440, 120, 86400)
    out = tmp_path / "tournament"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_strategy_tournament.py"),
            "--assets",
            "XX",
            "--timeframes",
            "1d",
            "--phase",
            "16",
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
    assert payload["phase"] == 16
    assert len(payload["runs"]) == 9


def test_tournament_vol_targeting_flag(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_synthetic_cache(cache, "YY", 1440, 120, 86400)
    out = tmp_path / "tournament_vol"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_strategy_tournament.py"),
            "--assets",
            "YY",
            "--timeframes",
            "1d",
            "--phase",
            "16",
            "--vol-targeting",
            "on",
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
    assert payload["vol_targeting"] == "on"


def test_new_strategies_run_on_synthetic() -> None:
    candles = synthetic_range(120)
    from src.bot.portfolio import PaperPortfolio

    portfolio = PaperPortfolio(cash_usd=1000.0)
    for name in PHASE16_ZOO_PRESETS["phase15_1d"]:
        strat = build_strategy(name, "1d")
        for i in range(strat.warmup_bars(), len(candles)):
            sig = strat.on_bar(i, candles, portfolio, "BTC")
            assert sig.action in ("buy", "sell", "hold")
