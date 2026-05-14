"""Market-data helpers built on top of the Kraken CLI wrapper.

Public API:
- get_available_xstocks() -> list[str]
- get_current_price(ticker) -> float
- get_ticker(ticker) -> dict
- get_ohlc(ticker, interval=60, count=24) -> list[dict]
- get_orderbook(ticker) -> dict   (best-effort, may be mocked)
"""

from __future__ import annotations

from typing import Any

from . import kraken_cli
from .logger import get_logger
from .universe import candidate_pair_forms, get_universe_tickers, normalize_symbol
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


def get_orderbook(ticker: str, quote: str = "USD", depth: int = 5) -> dict[str, Any]:
    forms = candidate_pair_forms(ticker, quote)
    for pair in forms:
        # TODO: confirm command name (kraken orderbook? kraken depth?).
        result = kraken_cli.run_cli(["orderbook", pair, "--depth", str(depth)])
        if result.ok and isinstance(result.stdout_json, dict):
            return {"source": "kraken_cli", "pair": pair, "data": result.stdout_json}
        if result.status == "missing_cli":
            break
    # Mock fallback derived from the ticker.
    t = get_ticker(ticker, quote)
    bid = safe_float(t.get("bid"))
    ask = safe_float(t.get("ask"))
    return {
        "source": "mock",
        "pair": normalize_symbol(ticker, quote).pair_slash,
        "data": {
            "bids": [[round(bid * (1 - 0.0002 * i), 4), 100 + 50 * i] for i in range(depth)],
            "asks": [[round(ask * (1 + 0.0002 * i), 4), 100 + 50 * i] for i in range(depth)],
        },
    }


__all__ = [
    "get_available_xstocks",
    "get_ticker",
    "get_ohlc",
    "get_current_price",
    "get_orderbook",
]
