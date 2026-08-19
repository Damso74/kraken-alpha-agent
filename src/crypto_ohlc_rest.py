"""Crypto OHLC fetcher backed by Kraken's public REST endpoint.

Why this exists
---------------
The xStocks-focused :mod:`src.kraken_ohlc_paginated` helper relies on the
``kraken ohlc`` CLI with ``--asset-class tokenized_asset``, which is the
only path Kraken exposes for tokenised equities. Crypto pairs do **not**
go through ``tokenized_asset``: the public REST endpoint
``https://api.kraken.com/0/public/OHLC`` works directly, requires no
authentication, and crucially is **not** blocked on PEDSL-CY accounts
the way the xStocks futures venue is.

This module is intentionally separate from the CLI wrapper so:

- The xStocks code paths are unchanged (zero behaviour regression on the
  240+ existing tests).
- We can run the crypto walk-forward fully offline-friendly: ``httpx``
  is already a project dependency, no new package required.
- The fetcher is injectable, so unit tests can drive the pagination
  state machine without hitting the network.

Hard safety contract
--------------------
- **Strictly read-only.** The endpoint exposes OHLC candles only — no
  authentication, no key, no chance of placing an order.
- Never imports :mod:`src.execution`, :mod:`src.risk`,
  :mod:`src.futures_kraken_cli` or any module that can mutate venue
  state.
- The HTTP layer uses a small, fixed timeout and a deterministic retry
  budget so a network flake cannot wedge the walk-forward driver.

Kraken depth caveats (empirical, May 2026)
------------------------------------------
The public REST endpoint exposes the same ~720-candle cap per call as
the CLI, and ``since`` cannot be used to reach back further than what
Kraken stores natively for each interval. Observed depth on ``XBTUSD``:

    ``interval=15``   → ~7.5 days
    ``interval=60``   → ~30 days
    ``interval=240``  → ~90 days
    ``interval=1440`` → multiple months

Forward pagination (advancing ``since`` to ``last_cursor``) lets us
stitch together a continuous span up to the depth wall, but cannot
recover history older than the wall.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .logger import get_logger

logger = get_logger(__name__)

# Kraken's public REST endpoint for candles. No authentication required.
KRAKEN_PUBLIC_OHLC_URL = "https://api.kraken.com/0/public/OHLC"

# Same per-call cap as the CLI wrapper.
KRAKEN_REST_OHLC_CAP_PER_CALL = 720

# Default per-call HTTP timeout in seconds.
DEFAULT_HTTP_TIMEOUT_SECONDS = 20.0

# Bare-ticker → Kraken REST pair convention. The REST endpoint accepts a
# small number of canonical aliases per pair; we use the compact form
# without the legacy ``X``/``Z`` prefixes (which Kraken accepts and then
# canonicalises internally to e.g. ``XXBTZUSD``). Tickers not in this
# table are passed through verbatim.
CRYPTO_TICKER_TO_REST_PAIR: dict[str, str] = {
    "BTC": "XBTUSD",
    "XBT": "XBTUSD",
    "ETH": "ETHUSD",
    "SOL": "SOLUSD",
    "AVAX": "AVAXUSD",
    "LTC": "LTCUSD",
    "XRP": "XRPUSD",
    "DOGE": "DOGEUSD",
    "LINK": "LINKUSD",
    "ADA": "ADAUSD",
    "DOT": "DOTUSD",
}


class CryptoOHLCFetchError(RuntimeError):
    """Raised when the public REST OHLC endpoint returns a Kraken error
    array or an unparseable payload."""


@dataclass
class OHLCRow:
    """Lightweight OHLC row, mirroring :class:`src.kraken_ohlc_paginated.OHLCRow`.

    The :meth:`as_market_data_dict` method produces the same dict shape
    that the backtester / walk-forward already consume, so the crypto
    payload can be fed directly into :func:`src.walk_forward.run_walk_forward`
    without any adapter.
    """

    timestamp: int
    open: float
    high: float
    low: float
    close: float
    vwap: float
    volume: float

    def as_market_data_dict(self) -> dict[str, float]:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "vwap": self.vwap,
            "volume": self.volume,
        }


def normalize_crypto_pair(ticker_or_pair: str) -> str:
    """Return the Kraken REST OHLC pair string for a crypto ticker or pair.

    Accepts both bare tickers (``"BTC"``, ``"ETH"``) and slash forms
    (``"BTC/USD"``, ``"ETH/USD"``). Unknown inputs are passed through
    uppercased and slash-stripped so the caller can experiment with new
    pairs without code changes.
    """
    if not ticker_or_pair:
        raise ValueError("ticker_or_pair must be non-empty")
    raw = ticker_or_pair.strip().upper()
    head, _, _ = raw.partition("/")
    return CRYPTO_TICKER_TO_REST_PAIR.get(head, head + "USD" if "/" in raw and "USD" in raw else head)


# Type alias for the injectable fetcher: (pair, interval_min, since) -> raw dict.
FetcherFn = Callable[[str, int, int | None], dict]


def default_rest_fetcher(
    pair: str,
    interval_min: int,
    since: int | None,
    *,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> dict:
    """Make a single Kraken public REST OHLC call. Returns the raw JSON dict.

    Raises :class:`CryptoOHLCFetchError` on transport failure or non-empty
    ``error`` array.
    """
    params: dict[str, Any] = {"pair": pair, "interval": int(interval_min)}
    if since is not None:
        params["since"] = int(since)
    try:
        response = httpx.get(
            KRAKEN_PUBLIC_OHLC_URL, params=params, timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise CryptoOHLCFetchError(
            f"transport error fetching OHLC for {pair}: {exc}"
        ) from exc
    if response.status_code != 200:
        raise CryptoOHLCFetchError(
            f"Kraken REST OHLC HTTP {response.status_code} for {pair}: "
            f"{response.text[:200]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise CryptoOHLCFetchError(
            f"Kraken REST OHLC returned non-JSON for {pair}: {exc}"
        ) from exc
    return payload


def parse_rest_ohlc_payload(
    payload: Any,
    *,
    pair_hint: str | None = None,
) -> tuple[list[OHLCRow], int | None]:
    """Parse a Kraken public REST OHLC payload into ``(rows, last_cursor)``.

    The REST shape is ``{"error": [...], "result": {"<canonical_pair>":
    [[ts, o, h, l, c, vwap, vol, trades], ...], "last": <ts>}}``. Kraken
    canonicalises the requested pair (e.g. ``XBTUSD`` → ``XXBTZUSD``) so
    we walk every key under ``result`` rather than relying on the hint.

    Rows are returned in ascending timestamp order. An empty payload
    yields ``([], None)`` rather than raising — the pagination loop
    treats that as "no progress" and stops cleanly.
    """
    if not isinstance(payload, dict):
        raise CryptoOHLCFetchError(
            f"OHLC payload is not a dict: {type(payload).__name__}"
        )

    err = payload.get("error")
    if isinstance(err, list) and err:
        raise CryptoOHLCFetchError(f"Kraken REST OHLC error: {err}")

    result = payload.get("result")
    if not isinstance(result, dict):
        return [], None

    last_cursor_raw = result.get("last")
    last_cursor = int(last_cursor_raw) if last_cursor_raw is not None else None

    candidate_keys: list[str] = []
    if pair_hint:
        candidate_keys.append(pair_hint)
    candidate_keys.extend(
        k for k in result.keys() if k not in {"last"} and k not in candidate_keys
    )

    candles_raw: list[Any] | None = None
    for key in candidate_keys:
        v = result.get(key)
        if isinstance(v, list):
            candles_raw = v
            break

    if candles_raw is None:
        return [], last_cursor

    rows: list[OHLCRow] = []
    for c in candles_raw:
        if not isinstance(c, list) or len(c) < 7:
            continue
        try:
            rows.append(
                OHLCRow(
                    timestamp=int(c[0]),
                    open=float(c[1]),
                    high=float(c[2]),
                    low=float(c[3]),
                    close=float(c[4]),
                    vwap=float(c[5]),
                    volume=float(c[6]),
                )
            )
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r.timestamp)
    if last_cursor is None and rows:
        last_cursor = rows[-1].timestamp
    return rows, last_cursor


def fetch_crypto_ohlc_paginated(
    pair: str,
    interval_min: int,
    target_candles: int,
    *,
    since: int | None = None,
    fetcher: FetcherFn | None = None,
    max_pages: int = 10,
    sleep_between_pages: float = 0.4,
) -> list[OHLCRow]:
    """Fetch up to ``target_candles`` rows by paginating Kraken REST forward.

    Pagination logic is identical to :func:`src.kraken_ohlc_paginated.fetch_ohlc_paginated`
    so consumers can swap the two helpers without behavioural surprise.
    Stops on any of:

    1. We collected ``target_candles`` rows.
    2. A page returned zero new rows (no progress).
    3. The ``last`` cursor did not advance between two consecutive calls.
    4. ``max_pages`` exhausted (defensive ceiling).

    ``sleep_between_pages`` introduces a small delay between successful
    pages so we never trip Kraken's anonymous rate limit on a long
    backfill — the public OHLC tier is generous but not infinite.

    Parameters
    ----------
    pair:
        Either a bare ticker (``"BTC"``), a slash pair (``"BTC/USD"``),
        or a canonical REST pair (``"XBTUSD"``). Bare tickers are
        normalised via :data:`CRYPTO_TICKER_TO_REST_PAIR`.
    interval_min:
        Candle interval in minutes (15, 60, 240, 1440).
    target_candles:
        Desired total rows. Effective cap; we never return more than
        this.
    since:
        Optional starting unix timestamp (seconds). When ``None`` the
        first call lets Kraken serve the most recent window. When set
        to a value within the natural depth window, pagination starts
        there and walks forward.
    fetcher:
        Injectable fetcher for unit tests. Defaults to
        :func:`default_rest_fetcher`.
    """
    if interval_min <= 0:
        raise ValueError(f"interval_min must be > 0 (got {interval_min})")
    if target_candles <= 0:
        raise ValueError(f"target_candles must be > 0 (got {target_candles})")

    rest_pair = normalize_crypto_pair(pair)
    f = fetcher or default_rest_fetcher

    accumulated: dict[int, OHLCRow] = {}
    cursor: int | None = since
    previous_cursor: int | None = None
    pages = 0

    while pages < max_pages and len(accumulated) < target_candles:
        pages += 1
        payload = f(rest_pair, interval_min, cursor)
        rows, last_cursor = parse_rest_ohlc_payload(payload, pair_hint=rest_pair)

        new_count = 0
        for r in rows:
            if r.timestamp not in accumulated:
                accumulated[r.timestamp] = r
                new_count += 1

        logger.debug(
            "crypto rest ohlc page %d pair=%s interval=%dm rows=%d new=%d total=%d cursor=%s last=%s",
            pages, rest_pair, interval_min, len(rows), new_count, len(accumulated),
            cursor, last_cursor,
        )

        if new_count == 0:
            break
        if (
            last_cursor is not None
            and previous_cursor is not None
            and last_cursor == previous_cursor
        ):
            break
        if last_cursor is None:
            break

        previous_cursor = last_cursor
        cursor = last_cursor

        if sleep_between_pages > 0 and pages < max_pages and len(accumulated) < target_candles:
            time.sleep(sleep_between_pages)

    out = sorted(accumulated.values(), key=lambda r: r.timestamp)
    if len(out) > target_candles:
        out = out[-target_candles:]
    return out


__all__ = [
    "KRAKEN_PUBLIC_OHLC_URL",
    "KRAKEN_REST_OHLC_CAP_PER_CALL",
    "CRYPTO_TICKER_TO_REST_PAIR",
    "CryptoOHLCFetchError",
    "OHLCRow",
    "FetcherFn",
    "default_rest_fetcher",
    "normalize_crypto_pair",
    "parse_rest_ohlc_payload",
    "fetch_crypto_ohlc_paginated",
]
