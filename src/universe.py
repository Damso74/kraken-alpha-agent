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

# Native crypto tickers kept verbatim (no auto ``x`` suffix). Used by the
# crypto-perps fallback profile when xStocks Spot/Futures are venue-blocked
# on the current Kraken account class. Crypto Perps trade 24/7.
KNOWN_CRYPTO_TICKERS: frozenset[str] = frozenset(
    {"BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX", "LINK", "ADA", "DOT", "LTC"}
)


@dataclass(frozen=True)
class UniverseSymbol:
    ticker: str          # e.g. "NVDAx"
    quote: str           # e.g. "USD"
    pair_slash: str      # e.g. "NVDAx/USD"
    pair_compact: str    # e.g. "NVDAxUSD"
    always_open: bool    # advertised as 24/7


def _strip_pair(raw: str) -> str:
    """Strip an optional ``/QUOTE`` tail so the caller can pass either a bare
    ticker (``BTC``) or a slash pair (``BTC/USD``) interchangeably."""
    if not raw:
        return ""
    head = raw.strip().split("/", 1)[0]
    return head


def normalize_symbol(ticker: str, quote: str = "USD") -> UniverseSymbol:
    raw = _strip_pair(ticker)
    upper = raw.upper()
    q = quote.strip().upper() or "USD"
    # Crypto path: keep the ticker verbatim (uppercased), do NOT auto-add
    # the ``x`` xStocks suffix. The Kraken Spot CLI accepts ``BTC/USD`` and
    # the Futures wrapper translates ``BTC`` to ``PF_XBTUSD``.
    if upper in KNOWN_CRYPTO_TICKERS:
        return UniverseSymbol(
            ticker=upper,
            quote=q,
            pair_slash=f"{upper}/{q}",
            pair_compact=f"{upper}{q}",
            always_open=True,
        )
    t = raw
    if not t.endswith("x"):
        # Allow accidental input like "TSLA" -> "TSLAx".
        t = f"{t}x"
    return UniverseSymbol(
        ticker=t,
        quote=q,
        pair_slash=f"{t}/{q}",
        pair_compact=f"{t}{q}",
        always_open=t in TWENTY_FOUR_SEVEN,
    )


def get_universe() -> list[UniverseSymbol]:
    cfg = get_settings().config.universe
    # Profile-level static override (crypto-perps fallback). When present,
    # entries are taken verbatim and the xStocks allowlist is bypassed.
    static = list(getattr(cfg, "static", []) or [])
    if static:
        return [normalize_symbol(s, cfg.quote) for s in static]
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


def build_dynamic_universe(rank_data, config) -> list[str]:
    """Filter and select the top-N opportunities from a ranking pass.

    Parameters
    ----------
    rank_data:
        Iterable of objects with the attributes produced by
        :mod:`src.ranking` — ``symbol``, ``spread_bps``, ``volume_24h``,
        ``trade_count_recent``, ``last_price``, ``opportunity_score``.
    config:
        Either a :class:`UniverseConfig` or a plain mapping with the same
        keys (``max_spread_bps``, ``min_volume``, ``min_trade_count``,
        ``top_n``, ``symbols``).

    Returns
    -------
    list[str]
        Ordered list of symbol tickers, length ≤ ``top_n``. When the dynamic
        filter yields no candidate (e.g. fully calm market), falls back to
        the static allowlist so the agent keeps making decisions.
    """
    # Lazy import to keep universe.py importable from ranking.py if needed.
    from .ranking import apply_filters, select_top_n

    def _attr(obj, name, default=None):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    max_spread = float(_attr(config, "max_spread_bps", 80))
    min_volume = float(_attr(config, "min_volume", 100))
    min_tc = int(_attr(config, "min_trade_count", 10))
    top_n = int(_attr(config, "top_n", 8))
    static_allow = list(_attr(config, "symbols", []) or [])

    ranked = list(rank_data) if rank_data is not None else []
    if not ranked:
        return static_allow[:top_n] if top_n else static_allow

    annotated = apply_filters(
        ranked,
        max_spread_bps=max_spread,
        min_volume=min_volume,
        min_trade_count=min_tc,
    )
    selected = select_top_n(annotated, top_n=top_n)
    if not selected:
        return static_allow[:top_n] if top_n else static_allow
    return [r.symbol for r in selected]


__all__ = [
    "UniverseSymbol",
    "normalize_symbol",
    "get_universe",
    "get_universe_tickers",
    "is_in_allowlist",
    "candidate_pair_forms",
    "pair_format",
    "build_dynamic_universe",
    "TWENTY_FOUR_SEVEN",
]
