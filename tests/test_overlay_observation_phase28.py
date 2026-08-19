"""Phase 28 — overlay observation daemon tests (no network, no live)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.bot.execution_simulator import ExecutionConfig
from src.bot.overlay_observation_engine import (
    STANDALONE_EQUITY_FILENAME,
    ObservationConfig,
    load_standalone_equity,
    replay_standalone_baseline,
    run_observation_once,
)
from src.bot.overlay_observation_kill import (
    OverlayKillConfig,
    evaluate_overlay_kill,
    observation_stop_active,
    write_observation_stop,
)
from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio
from src.strategies.trend_following import TrendFollowingStrategy

REPO = Path(__file__).resolve().parents[1]
EXEC_CFG = ExecutionConfig(fee_bps=40.0, slippage_bps=5.0)


def crossover_candles() -> list[BotCandle]:
    """Serie deterministe: baisse, hausse, baisse.

    SMA20 croise SMA50 une fois a la hausse puis une fois a la baisse — donc
    exactement un 'buy' puis un 'sell' pour la strategie standalone.
    """
    prices: list[float] = []
    price = 200.0
    for _ in range(60):
        price -= 1.0
        prices.append(price)
    for _ in range(80):
        price += 1.0
        prices.append(price)
    for _ in range(80):
        price -= 1.0
        prices.append(price)
    t0 = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp())
    return [
        BotCandle(
            timestamp=t0 + i * 14400,
            open=p,
            high=p + 1.0,
            low=p - 1.0,
            close=p,
            volume=10.0,
        )
        for i, p in enumerate(prices)
    ]


def _standalone_strategy() -> TrendFollowingStrategy:
    strat = TrendFollowingStrategy()
    # 10% d'exposition: le garde-fou max_position_fraction du RiskManager (25%)
    # ne peut pas refuser la sortie apres une hausse, on teste bien le replay.
    strat.max_position_fraction = 0.10
    return strat


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


def test_standalone_replay_emits_buy_then_sell() -> None:
    """Le baseline standalone doit franchir buy PUIS sell (defaut #1).

    Sans replay reel, portfolio_standalone reste vide: la garde
    ``pos.quantity > 1e-12`` interdit tout 'sell' et un 'buy' est re-emis a
    chaque barre haussiere.
    """
    candles = crossover_candles()
    strat = _standalone_strategy()
    actions: list[tuple[int, str]] = []
    for idx in range(strat.warmup_bars(), len(candles)):
        portfolio = PaperPortfolio(cash_usd=1000.0)
        signal, curve = replay_standalone_baseline(
            _standalone_strategy(),
            candles,
            portfolio,
            symbol="ETH",
            exec_cfg=EXEC_CFG,
            bar_index=idx,
            starting_equity=1000.0,
            timeframe="4h",
        )
        assert len(curve) == idx + 1
        if signal is not None and signal.action in ("buy", "sell"):
            actions.append((idx, signal.action))

    assert [a for _, a in actions] == ["buy", "sell"]
    buy_idx, sell_idx = actions[0][0], actions[1][0]
    assert buy_idx < sell_idx


def test_standalone_replay_holds_position_between_crossovers() -> None:
    """Entre les deux croisements la position standalone reste ouverte."""
    candles = crossover_candles()
    portfolio = PaperPortfolio(cash_usd=1000.0)
    signal, _ = replay_standalone_baseline(
        _standalone_strategy(),
        candles,
        portfolio,
        symbol="ETH",
        exec_cfg=EXEC_CFG,
        bar_index=120,
        starting_equity=1000.0,
        timeframe="4h",
    )
    assert portfolio.position("ETH").quantity > 1e-12
    assert signal is not None and signal.action == "hold"


def test_observation_once_persists_standalone_curve(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_eth4h_cache(cache)
    state = tmp_path / "state"
    out = run_observation_once(ObservationConfig(state_dir=state, cache_root=cache))
    assert out["status"] == "ok"
    assert (state / STANDALONE_EQUITY_FILENAME).is_file()
    assert load_standalone_equity(state) == [out["standalone_equity"]]
    assert out["kill"]["standalone_comparison"]["status"] == "evaluated"


def test_kill_underperformance_triggers() -> None:
    result = evaluate_overlay_kill(
        "nonexistent_state_dir_for_test",
        overlay_equity_curve=[1000.0, 1000.0, 1000.0],
        standalone_equity_curve=[1000.0, 1050.0, 1100.0],
        stop_file=Path("nonexistent_stop_file_for_test"),
    )
    assert result.metrics["standalone_comparison"]["status"] == "evaluated"
    assert any("overlay_underperforms_standalone" in r for r in result.reasons)


def test_kill_underperformance_not_triggered() -> None:
    result = evaluate_overlay_kill(
        "nonexistent_state_dir_for_test",
        overlay_equity_curve=[1000.0, 1050.0, 1100.0],
        standalone_equity_curve=[1000.0, 1000.0, 1000.0],
        stop_file=Path("nonexistent_stop_file_for_test"),
    )
    assert result.metrics["standalone_comparison"]["status"] == "evaluated"
    assert not any("overlay_underperforms_standalone" in r for r in result.reasons)
    assert result.metrics["equity_gap_pct"] > 0


def test_kill_underperformance_not_evaluable() -> None:
    """Sans courbe standalone le critere est explicitement non evaluable."""
    result = evaluate_overlay_kill(
        "nonexistent_state_dir_for_test",
        overlay_equity_curve=[1000.0, 1050.0],
        standalone_equity_curve=None,
        stop_file=Path("nonexistent_stop_file_for_test"),
    )
    comparison = result.metrics["standalone_comparison"]
    assert comparison["status"] == "not_evaluable"
    assert comparison["reason"] == "standalone_curve_missing"
    assert result.metrics["equity_gap_pct"] is None
    assert not any("overlay_underperforms_standalone" in r for r in result.reasons)


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
    for _ in range(10):
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
