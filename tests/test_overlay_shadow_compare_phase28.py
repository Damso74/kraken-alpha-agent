"""Phase 28 — overlay shadow comparison unit tests."""

from __future__ import annotations

from dataclasses import asdict

from src.bot.basis_crowding_overlay import BasisCrowdingState
from src.bot.execution_simulator import ExecutionConfig
from src.bot.overlay_observation_engine import replay_standalone_baseline
from src.bot.overlay_shadow_compare import (
    ShadowComparisonRecord,
    append_shadow_comparison,
    build_shadow_record,
    load_shadow_comparisons,
    overlay_blocks_trade,
    summarize_shadow,
)
from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio
from src.strategies.base import StrategySignal
from src.strategies.trend_following import TrendFollowingStrategy


def _crossover_candles() -> list[BotCandle]:
    """Baisse, hausse, baisse: un seul croisement haussier puis un seul baissier."""
    prices: list[float] = []
    price = 200.0
    for delta, count in ((-1.0, 60), (1.0, 80), (-1.0, 80)):
        for _ in range(count):
            price += delta
            prices.append(price)
    return [
        BotCandle(
            timestamp=1_672_531_200 + i * 14400,
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
    strat.max_position_fraction = 0.10
    return strat


def test_would_trade_bars_match_crossovers_only() -> None:
    """standalone_would_trade ne doit etre vrai que sur les croisements.

    Avec le portefeuille standalone vide (bug du replay no-op), la strategie
    re-emettait 'buy' sur chaque barre haussiere: le comptage explosait.
    """
    candles = _crossover_candles()
    allow_state = BasisCrowdingState("allow", 0.2, 0.1, False, False, "neutral")
    warmup = _standalone_strategy().warmup_bars()
    records = []
    for idx in range(warmup, len(candles)):
        signal, _ = replay_standalone_baseline(
            _standalone_strategy(),
            candles,
            PaperPortfolio(cash_usd=1000.0),
            symbol="ETH",
            exec_cfg=ExecutionConfig(fee_bps=40.0, slippage_bps=5.0),
            bar_index=idx,
            starting_equity=1000.0,
            timeframe="4h",
        )
        records.append(
            build_shadow_record(
                timestamp=int(candles[idx].timestamp),
                price=float(candles[idx].close),
                standalone_sig=signal,
                overlay_sig=signal,
                overlay_state=allow_state,
                bar_index=idx,
                warmup=warmup,
                buy_hold_in_market=idx > warmup,
            )
        )

    traded = [r for r in records if r.standalone_would_trade]
    assert [r.standalone_action for r in traded] == ["buy", "sell"]
    assert summarize_shadow([asdict(r) for r in records])["standalone_trades"] == 2


def test_build_shadow_record_allow() -> None:
    standalone = StrategySignal("buy", 0.25, "trend_up")
    overlay = StrategySignal("buy", 0.25, "ok")
    state = BasisCrowdingState("allow", 0.2, 0.1, False, False, "neutral")
    rec = build_shadow_record(
        timestamp=1_700_000_000,
        price=2000.0,
        standalone_sig=standalone,
        overlay_sig=overlay,
        overlay_state=state,
        bar_index=80,
        warmup=65,
        buy_hold_in_market=False,
    )
    assert rec.raw_signal == "buy"
    assert rec.overlay_decision == "allow"
    assert rec.standalone_would_trade is True
    assert rec.overlay_blocks is False
    assert rec.effective_action == "buy"


def test_overlay_blocks_on_block_filter() -> None:
    standalone = StrategySignal("buy", 0.25, "trend_up")
    overlay = StrategySignal("hold", 0.0, "basis_crowding_block")
    state = BasisCrowdingState("block", 2.5, 2.5, False, False, "elevated")
    assert overlay_blocks_trade(standalone, state, overlay) is True


def test_append_and_summarize(tmp_path) -> None:
    rec = ShadowComparisonRecord(
        timestamp=1,
        price=100.0,
        raw_signal="buy",
        standalone_action="buy",
        overlay_decision="block",
        overlay_reason="test",
        funding_z=2.5,
        basis_z=2.0,
        standalone_would_trade=True,
        overlay_blocks=True,
        effective_action="hold",
        buy_and_hold_action="buy",
        cash_action="hold",
    )
    append_shadow_comparison(tmp_path, rec)
    rows = load_shadow_comparisons(tmp_path)
    assert len(rows) == 1
    summary = summarize_shadow(rows)
    assert summary["blocks"] == 1
    assert summary["standalone_trades"] == 1
    assert summary["block_rate_on_signals"] == 1.0
