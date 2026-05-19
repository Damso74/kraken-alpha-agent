"""Shared synthetic candle fixtures for bot tests."""

from __future__ import annotations

from src.bot.paper_engine import BotCandle


def synthetic_uptrend(n: int = 120, start: float = 100.0) -> list[BotCandle]:
    candles: list[BotCandle] = []
    price = start
    for i in range(n):
        price *= 1.002
        candles.append(
            BotCandle(
                timestamp=i,
                open=price * 0.999,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=1000.0,
            )
        )
    return candles


def synthetic_range(n: int = 120, mid: float = 100.0) -> list[BotCandle]:
    candles: list[BotCandle] = []
    for i in range(n):
        swing = mid + (i % 10 - 5) * 0.5
        candles.append(
            BotCandle(
                timestamp=i,
                open=swing,
                high=swing + 1,
                low=swing - 1,
                close=swing,
                volume=500.0,
            )
        )
    return candles
