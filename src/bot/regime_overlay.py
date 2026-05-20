"""Regime risk overlay for a single low-frequency strategy (Phase 23D)."""

from __future__ import annotations

from typing import Any, Sequence

from src.bot.regime_classifier import classify_regime
from src.bot.regime_features import (
    RegimeFeatures,
    compute_regime_features,
    precompute_regime_features,
)
from src.bot.regime_router import DEFAULT_MAX_POSITION
from src.strategies.base import StrategySignal


class RegimeOverlayStrategy:
    """Scale or flatten a base strategy by regime — not a strategy picker."""

    name = "regime_overlay"

    def __init__(
        self,
        inner: object,
        timeframe: str,
        *,
        ma_window: int = 50,
        precomputed_features: Sequence[RegimeFeatures | None] | None = None,
        cache_regime_features: bool = False,
    ) -> None:
        self._inner = inner
        self.timeframe = timeframe
        self.ma_window = ma_window
        inner_name = getattr(inner, "name", "strategy")
        self.name = f"{inner_name}+regime_overlay"
        self._precomputed: list[RegimeFeatures | None] | None = (
            list(precomputed_features) if precomputed_features is not None else None
        )
        self._cache_regime_features = cache_regime_features
        self._candles_id: int | None = None

    def bind_candles(self, candles: Sequence[Any]) -> None:
        if self._precomputed is not None:
            return
        use_cache = self._cache_regime_features or len(candles) <= 1200
        if not use_cache:
            return
        cid = id(candles)
        if self._candles_id == cid and self._precomputed is not None:
            return
        self._precomputed = precompute_regime_features(candles, ma_window=self.ma_window)
        self._candles_id = cid

    def warmup_bars(self) -> int:
        return max(int(getattr(self._inner, "warmup_bars")()), self.ma_window + 5)

    def _scale_for_regime(self, regime: str) -> float:
        if regime == "trend_up":
            return 1.0
        if regime == "high_vol":
            return 0.25
        if regime in ("panic", "range"):
            return 0.0
        return 0.5

    def on_bar(self, index, candles, portfolio, symbol) -> StrategySignal | None:
        self.bind_candles(candles)
        if self._precomputed is not None and index < len(self._precomputed):
            features = self._precomputed[index]
        else:
            features = compute_regime_features(candles, index, ma_window=self.ma_window)
        classification = classify_regime(features)
        regime = classification.regime
        scale = self._scale_for_regime(regime)

        if scale <= 0.0:
            pos = portfolio.position(symbol)
            if pos.quantity > 1e-12:
                return StrategySignal("sell", 1.0, f"overlay_{regime}_exit")
            return StrategySignal("hold", 0.0, f"overlay_{regime}_cash")

        sig = self._inner.on_bar(index, candles, portfolio, symbol)
        if sig is None or sig.action == "hold":
            return sig
        if sig.action == "sell":
            return sig
        scaled = min(DEFAULT_MAX_POSITION, float(sig.size_fraction) * scale)
        return StrategySignal(
            sig.action,
            scaled,
            f"overlay_{regime}:{sig.reason}",
        )
