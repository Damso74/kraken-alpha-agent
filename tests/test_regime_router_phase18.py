"""Tests for regime router (Phase 18)."""

from __future__ import annotations

from src.bot.portfolio import PaperPortfolio
from src.bot.regime_classifier import RegimeClassification
from src.bot.regime_router import RegimeRouterStrategy, route_regime
from tests.conftest_bot import synthetic_uptrend


def test_route_trend_up() -> None:
    d = route_regime(RegimeClassification("trend_up", 0.8, "test"))
    assert d.selected_strategy in ("trend_following", "ema_crossover", "donchian_breakout")
    assert d.position_scale == 1.0


def test_route_panic_cash() -> None:
    d = route_regime(RegimeClassification("panic", 0.9, "test"))
    assert d.selected_strategy == "cash"
    assert d.position_scale == 0.0


def test_regime_router_strategy_runs() -> None:
    candles = synthetic_uptrend(80)
    router = RegimeRouterStrategy("1d")
    portfolio = PaperPortfolio(cash_usd=1000.0)
    sig = router.on_bar(router.warmup_bars(), candles, portfolio, "BTC")
    assert sig is None or sig.action in ("buy", "sell", "hold")
