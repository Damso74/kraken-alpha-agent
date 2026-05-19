"""Mean-reversion strategy — fades extreme short-horizon moves."""

from __future__ import annotations

from ..schemas import Features, StrategyVote
from ..utils import clamp


def score(features: Features) -> StrategyVote:
    # Strong 15m move tends to revert — sign is inverted.
    r15 = features.return_15m
    r1h = features.return_1h
    overshoot = (r15 - r1h * 0.3)
    raw = -clamp(overshoot / 0.01, -1.0, 1.0)
    confidence = clamp(abs(overshoot) / 0.005, 0.0, 1.0)
    # Don't fade when 15m and 1h agree (likely a real trend).
    if r15 * r1h > 0 and abs(r1h) >= 0.005:
        confidence *= 0.5
    rationale = (
        f"overshoot15m_vs_1h={overshoot:+.4f} -> fade_score={raw:+.3f}"
    )
    return StrategyVote(
        name="mean_reversion",
        score=raw,
        confidence=confidence,
        rationale=rationale,
    )


# --- Phase 14 paper-bot (z-score mean reversion) ---------------------------


from typing import Sequence  # noqa: E402

from src.bot.paper_engine import BotCandle  # noqa: E402
from src.bot.portfolio import PaperPortfolio  # noqa: E402

from .base import StrategySignal  # noqa: E402


class MeanReversionStrategy:
    """Z-score fade with max holding period (bars ≈ days on 1d data)."""

    name = "mean_reversion"
    lookback = 20
    entry_z = 1.5
    exit_z = 0.25
    max_holding_bars = 7
    max_position_fraction = 0.25

    def warmup_bars(self) -> int:
        return self.lookback + 1

    def _zscore(self, closes: list[float]) -> float | None:
        if len(closes) < self.lookback:
            return None
        window = closes[-self.lookback :]
        mean = sum(window) / len(window)
        var = sum((x - mean) ** 2 for x in window) / len(window)
        if var <= 1e-18:
            return 0.0
        std = var**0.5
        return (closes[-1] - mean) / std

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None:
        closes = [c.close for c in candles[: index + 1]]
        z = self._zscore(closes)
        if z is None:
            return StrategySignal("hold", 0.0, "warming up")

        pos = portfolio.position(symbol)
        if pos.quantity > 1e-12 and pos.bars_held >= self.max_holding_bars:
            return StrategySignal("sell", 1.0, "max holding period")

        if z <= -self.entry_z and pos.quantity <= 1e-12:
            return StrategySignal(
                "buy",
                self.max_position_fraction,
                f"z={z:.2f} oversold",
            )
        if pos.quantity > 1e-12 and (z >= -self.exit_z or z >= self.entry_z):
            return StrategySignal("sell", 1.0, f"z={z:.2f} exit")
        return StrategySignal("hold", 0.0, f"z={z:.2f}")

