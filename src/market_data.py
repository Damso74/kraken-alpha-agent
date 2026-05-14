"""Market-data helpers built on top of the Kraken CLI wrapper.

Public API:
- get_available_xstocks() -> list[str]
- get_current_price(ticker) -> float
- get_ticker(ticker) -> dict
- get_ohlc(ticker, interval=60, count=24) -> list[dict]
- get_orderbook(ticker, count=10) -> dict
- get_trades(ticker, count=20) -> dict
"""

from __future__ import annotations

from typing import Any

from . import kraken_cli
from .logger import get_logger
from .universe import get_universe_tickers
from .utils import safe_float

logger = get_logger(__name__)


def get_available_xstocks() -> list[str]:
    return get_universe_tickers()


def get_ticker(ticker: str, quote: str = "USD") -> dict[str, Any]:
    return kraken_cli.fetch_ticker(ticker, quote)


def get_ohlc(
    ticker: str, quote: str = "USD", interval_minutes: int = 60, count: int = 24
) -> list[dict[str, float]]:
    return kraken_cli.fetch_ohlc(ticker, quote, interval_minutes, count)


def get_current_price(ticker: str, quote: str = "USD") -> float:
    info = get_ticker(ticker, quote)
    return safe_float(info.get("last"))


def get_orderbook(ticker: str, quote: str = "USD", count: int = 10) -> dict[str, Any]:
    return kraken_cli.fetch_orderbook(ticker, quote, count)


def get_trades(ticker: str, quote: str = "USD", count: int = 20) -> dict[str, Any]:
    return kraken_cli.fetch_trades(ticker, quote, count)


__all__ = [
    "get_available_xstocks",
    "get_ticker",
    "get_ohlc",
    "get_current_price",
    "get_orderbook",
    "get_trades",
]
