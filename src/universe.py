"""xStocks universe helpers.

xStocks are tokenised representations of US equities/ETFs. We hold an explicit
allowlist (from `config.yaml`) and a thin normalisation layer that produces
the candidate pair-symbols the Kraken CLI is most likely to accept.

The exact on-the-wire symbol format on the CLI is not 100% documented; the
common Kraken Pro conventions are either ``TICKERx/QUOTE`` (slash form) or
``TICKERxQUOTE`` (compact form). The wrapper retries the second form if the
first one fails — see ``kraken_cli.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import get_settings


# xStocks advertised as 24/7 in Kraken's xStocks FAQ.
TWENTY_FOUR_SEVEN: frozenset[str] = frozenset(
    {"TSLAx", "QQQx", "SPYx", "NVDAx", "CRCLx", "AAPLx", "HOODx", "MSTRx", "GLDx", "GOOGLx"}
)


@dataclass(frozen=True)
class UniverseSymbol:
    ticker: str          # e.g. "NVDAx"
    quote: str           # e.g. "USD"
    pair_slash: str      # e.g. "NVDAx/USD"
    pair_compact: str    # e.g. "NVDAxUSD"
    always_open: bool    # advertised as 24/7


def normalize_symbol(ticker: str, quote: str = "USD") -> UniverseSymbol:
    t = ticker.strip()
    if not t.endswith("x"):
        # Allow accidental input like "TSLA" -> "TSLAx".
        t = f"{t}x"
    q = quote.strip().upper() or "USD"
    return UniverseSymbol(
        ticker=t,
        quote=q,
        pair_slash=f"{t}/{q}",
        pair_compact=f"{t}{q}",
        always_open=t in TWENTY_FOUR_SEVEN,
    )


def get_universe() -> list[UniverseSymbol]:
    cfg = get_settings().config.universe
    return [normalize_symbol(s, cfg.quote) for s in cfg.symbols]


def get_universe_tickers() -> list[str]:
    return [u.ticker for u in get_universe()]


def is_in_allowlist(ticker: str) -> bool:
    return ticker in get_universe_tickers()


def candidate_pair_forms(ticker: str, quote: str = "USD") -> list[str]:
    """Return the pair-symbol forms to try against the Kraken CLI, in order.

    Officially confirmed against ``kraken 0.3.2``: the slash form
    (e.g. ``AAPLx/USD``) is what the Kraken CLI exposes for xStocks ticker /
    ohlc / orderbook / trades / order subcommands. We still attempt the
    compact form as a defensive retry in case some operation requires it.
    """
    sym = normalize_symbol(ticker, quote)
    return [sym.pair_slash, sym.pair_compact]


def pair_format(ticker: str, quote: str = "USD") -> str:
    """Return the official Kraken CLI pair form for an xStocks ticker."""
    return normalize_symbol(ticker, quote).pair_slash


__all__ = [
    "UniverseSymbol",
    "normalize_symbol",
    "get_universe",
    "get_universe_tickers",
    "is_in_allowlist",
    "candidate_pair_forms",
    "pair_format",
    "TWENTY_FOUR_SEVEN",
]
