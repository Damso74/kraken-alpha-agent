"""Regime-based strategy router for paper backtests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.bot.regime_classifier import RegimeClassification, RegimeLabel, classify_regime
from src.bot.regime_features import (
    RegimeFeatures,
    compute_regime_features,
    precompute_regime_features,
)
from src.strategies.base import StrategySignal
from src.strategies.presets import build_strategy

TREND_STRATEGIES = ("trend_following", "ema_crossover", "donchian_breakout")
RANGE_STRATEGIES = ("grid", "mean_reversion", "bollinger_mean_reversion", "rsi_mean_reversion")
DEFAULT_MAX_POSITION = 0.25


@dataclass(frozen=True)
class RouterDecision:
    regime: RegimeLabel
    selected_strategy: str
    position_scale: float
    reason: str


def route_regime(
    classification: RegimeClassification,
    *,
    available_strategies: Sequence[str] | None = None,
) -> RouterDecision:
    avail = set(available_strategies or (*TREND_STRATEGIES, *RANGE_STRATEGIES))
    regime = classification.regime

    if regime == "trend_up":
        for name in TREND_STRATEGIES:
            if name in avail:
                return RouterDecision(regime, name, 1.0, classification.reason)
        return RouterDecision(regime, "trend_following", 1.0, "fallback_trend")

    if regime == "range":
        for name in RANGE_STRATEGIES:
            if name in avail:
                return RouterDecision(regime, name, 1.0, classification.reason)
        return RouterDecision(regime, "mean_reversion", 1.0, "fallback_range")

    if regime == "high_vol":
        return RouterDecision(regime, "cash", 0.25, "reduce_exposure_high_vol")

    if regime == "panic":
        return RouterDecision(regime, "cash", 0.0, "panic_cash")

    return RouterDecision(regime, "cash", 0.0, "unknown_hold")


class RegimeRouterStrategy:
    """Strategy adapter that delegates to regime-selected sub-strategy."""

    name = "regime_router"

    def __init__(
        self,
        timeframe: str,
        *,
        available_strategies: Sequence[str] | None = None,
        ma_window: int = 50,
        precomputed_features: Sequence[RegimeFeatures | None] | None = None,
        cache_regime_features: bool = False,
    ) -> None:
        self.timeframe = timeframe
        self.available = tuple(available_strategies or (*TREND_STRATEGIES, *RANGE_STRATEGIES))
        self.ma_window = ma_window
        self._strategies: dict[str, Any] = {}
        self._last_regime: RegimeLabel = "unknown"
        self._active_name: str = "cash"
        self.decision_log: list[dict[str, Any]] = []
        self._precomputed: list[RegimeFeatures | None] | None = (
            list(precomputed_features) if precomputed_features is not None else None
        )
        self._cache_regime_features = cache_regime_features
        self._candles_id: int | None = None

    def bind_candles(self, candles: Sequence[Any]) -> None:
        """Optional warmup: precompute features once per candle series."""
        if self._precomputed is not None:
            return
        if not self._cache_regime_features:
            return
        cid = id(candles)
        if self._candles_id == cid and self._precomputed is not None:
            return
        self._precomputed = precompute_regime_features(candles, ma_window=self.ma_window)
        self._candles_id = cid

    def warmup_bars(self) -> int:
        return self.ma_window + 5

    def _get_strategy(self, name: str):
        if name == "cash":
            return None
        if name not in self._strategies:
            self._strategies[name] = build_strategy(name, self.timeframe)
        return self._strategies[name]

    def on_bar(self, index, candles, portfolio, symbol) -> StrategySignal | None:
        self.bind_candles(candles)
        if self._precomputed is not None and index < len(self._precomputed):
            features = self._precomputed[index]
        else:
            features = compute_regime_features(candles, index, ma_window=self.ma_window)
        classification = classify_regime(features)
        decision = route_regime(classification, available_strategies=self.available)

        if decision.selected_strategy != self._active_name or decision.regime != self._last_regime:
            self.decision_log.append(
                {
                    "bar_index": index,
                    "regime": decision.regime,
                    "selected_strategy": decision.selected_strategy,
                    "position_scale": decision.position_scale,
                    "reason": decision.reason,
                }
            )
        self._active_name = decision.selected_strategy
        self._last_regime = decision.regime

        if decision.selected_strategy == "cash" or decision.position_scale <= 0:
            pos = portfolio.position(symbol)
            if pos.quantity > 1e-12:
                return StrategySignal("sell", 1.0, f"regime_{decision.regime}_exit")
            return StrategySignal("hold", 0.0, f"regime_{decision.regime}_cash")

        inner = self._get_strategy(decision.selected_strategy)
        if inner is None:
            return StrategySignal("hold", 0.0, "no_strategy")

        sig = inner.on_bar(index, candles, portfolio, symbol)
        if sig is None or sig.action == "hold":
            return sig
        scaled = min(
            DEFAULT_MAX_POSITION,
            float(sig.size_fraction) * decision.position_scale,
        )
        return StrategySignal(
            sig.action,
            scaled,
            f"router_{decision.regime}:{decision.selected_strategy}:{sig.reason}",
        )


class BuyAndHoldStrategy:
    name = "buy_and_hold"

    def __init__(self, size_fraction: float = 0.25) -> None:
        self.size_fraction = size_fraction
        self._bought = False

    def warmup_bars(self) -> int:
        return 1

    def on_bar(self, index, candles, portfolio, symbol) -> StrategySignal | None:
        if self._bought:
            return StrategySignal("hold", 0.0, "hold")
        pos = portfolio.position(symbol)
        if pos.quantity > 1e-12:
            self._bought = True
            return StrategySignal("hold", 0.0, "hold")
        self._bought = True
        return StrategySignal("buy", self.size_fraction, "buy_and_hold_entry")


class CashStrategy:
    name = "cash"

    def warmup_bars(self) -> int:
        return 1

    def on_bar(self, index, candles, portfolio, symbol) -> StrategySignal | None:
        pos = portfolio.position(symbol)
        if pos.quantity > 1e-12:
            return StrategySignal("sell", 1.0, "cash_flatten")
        return StrategySignal("hold", 0.0, "cash")
