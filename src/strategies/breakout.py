"""Breakout strategy — distance from the 1h high/low."""

from __future__ import annotations

from ..schemas import Features, StrategyVote
from ..utils import clamp


def score(features: Features) -> StrategyVote:
    # Proximity is 1.0 when the price sits exactly on the 1h extreme and 0
    # when it is more than ~50bps away. The breakout score is just the
    # difference: positive near the high, negative near the low.
    threshold = 0.005
    prox_high = clamp(1.0 - features.distance_from_high_1h / threshold, 0.0, 1.0)
    prox_low = clamp(1.0 - features.distance_from_low_1h / threshold, 0.0, 1.0)
    saturated = clamp(prox_high - prox_low, -1.0, 1.0)
    confidence = clamp(max(prox_high, prox_low), 0.0, 1.0)
    rationale = (
        f"dist_high={features.distance_from_high_1h:.4f} "
        f"dist_low={features.distance_from_low_1h:.4f} -> "
        f"prox_high={prox_high:.3f} prox_low={prox_low:.3f}"
    )
    return StrategyVote(
        name="breakout",
        score=saturated,
        confidence=confidence,
        rationale=rationale,
    )


# --- Phase 14 paper-bot (rolling high/low on OHLC) -------------------------


from typing import Sequence  # noqa: E402

from src.bot.paper_engine import BotCandle  # noqa: E402
from src.bot.portfolio import PaperPortfolio  # noqa: E402

from .base import StrategySignal  # noqa: E402


class BreakoutStrategy:
    """Rolling high/low breakout for paper backtests."""

    name = "breakout"
    lookback = 20
    max_position_fraction = 0.25

    def warmup_bars(self) -> int:
        return self.lookback + 1

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        window = candles[max(0, index - self.lookback + 1) : index + 1]
        if len(window) < self.lookback:
            return StrategySignal("hold", 0.0, "warming up")
        highs = [c.high for c in window]
        lows = [c.low for c in window]
        roll_high = max(highs[:-1]) if len(highs) > 1 else highs[0]
        roll_low = min(lows[:-1]) if len(lows) > 1 else lows[0]
        close = window[-1].close
        pos = portfolio.position(symbol)

        if close > roll_high and pos.quantity <= 1e-12:
            return StrategySignal(
                "buy",
                self.max_position_fraction,
                f"close>{roll_high:.4f}",
            )
        if close < roll_low and pos.quantity > 1e-12:
            return StrategySignal("sell", 1.0, f"close<{roll_low:.4f}")
        return StrategySignal("hold", 0.0, "inside range")
