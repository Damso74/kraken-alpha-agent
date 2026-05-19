"""Base types for Phase 14 paper-bot strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence

from src.bot.paper_engine import BotCandle
from src.bot.portfolio import PaperPortfolio

Action = Literal["buy", "sell", "hold"]


@dataclass(frozen=True)
class StrategySignal:
    action: Action
    size_fraction: float
    reason: str = ""


class BaseStrategy(Protocol):
    name: str

    def warmup_bars(self) -> int: ...

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> StrategySignal | None: ...
