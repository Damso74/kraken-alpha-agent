"""Paginated OHLC fetcher for Kraken xStocks.

Why this module exists
----------------------
Kraken's CLI ``kraken ohlc <pair> --interval N`` (kraken 0.3.2) returns at most
~720 candles per call. Two practical observations:

1. When ``--since`` is **inside** the live ~720 candle window, Kraken honours it
   and returns rows starting at-or-after that timestamp. We can therefore
   advance ``--since`` after each batch to stitch a longer span (forward
   pagination), which is useful when we want to assemble a richer dataset
   without bumping into the per-call cap.

2. When ``--since`` is **older** than that window, Kraken silently returns the
   most recent ~720 candles anyway — the public surface does not expose the
   deeper history. So forward pagination cannot recover history older than
   what Kraken stores natively for each interval.

   Empirical depth (kraken 0.3.2, May 2026, AAPLx/USD):
       ``--interval 15``   → ~7.5 days
       ``--interval 60``   → ~30 days
       ``--interval 240``  → ~120 days
       ``--interval 1440`` → ~9 months

The Kraken **public REST** OHLC endpoint also rejects tokenized_asset pairs
with ``EGeneral:Invalid arguments`` (verified May 2026). The CLI is the only
working surface, so this module wraps the existing ``run_cli`` helper rather
than calling REST directly. The module never reads ``.env``: ``run_cli`` uses
whichever credentials are already configured in the user's ``kraken``
installation, and OHLC is read-only.

Public API
----------
- :class:`OHLCRow`           Lightweight row struct with the same fields as
                             ``src.market_data.get_ohlc`` returns (``timestamp``,
                             ``open``, ``high``, ``low``, ``close``, ``vwap``,
                             ``volume``).
- :func:`parse_ohlc_payload` Pure function: convert a Kraken-shaped JSON dict
                             ``{"<pair>": [...], "last": <ts>}`` into rows +
                             cursor. Raises :class:`OHLCFetchError` if the
                             payload contains a non-empty ``error`` array.
- :func:`fetch_ohlc_paginated`
                             High-level loop that calls a fetcher repeatedly,
                             advancing the ``since`` cursor between calls.
                             ``fetcher`` is injectable so unit tests can drive
                             the pagination state machine without subprocesses.
- :func:`default_cli_fetcher`
                             The production fetcher; calls ``run_cli`` and
                             returns the parsed dict. Tests **do not** use it.

Safety
------
- Read-only: never invokes ``kraken order``, ``kraken paper``,
  ``kraken futures``, or anything that mutates state on Kraken.
- Never imports ``src.execution`` / ``src.risk`` / ``src.main`` etc.
- Idempotent: same call returns equivalent rows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .kraken_cli import run_cli
from .logger import get_logger
from .universe import candidate_pair_forms

logger = get_logger(__name__)

# Kraken caps each OHLC response at this many candles (kraken 0.3.2).
KRAKEN_OHLC_CAP_PER_CALL = 720


class OHLCFetchError(RuntimeError):
    """Raised when Kraken returns a non-empty error array or an unparseable payload."""


@dataclass
class OHLCRow:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    vwap: float
    volume: float

    def as_market_data_dict(self) -> dict[str, float]:
        """Match the dict shape that :mod:`src.market_data` already returns."""
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "vwap": self.vwap,
            "volume": self.volume,
        }


# Type alias for the injectable fetcher: (pair, interval_min, since) -> raw dict.
FetcherFn = Callable[[str, int, int | None], dict]


def parse_ohlc_payload(
    payload: Any,
    *,
    pair_hint: str | None = None,
) -> tuple[list[OHLCRow], int | None]:
    """Parse a Kraken OHLC JSON payload into ``(rows, last_cursor)``.

    Accepts both the canonical CLI shape ``{"AAPLx/USD": [...], "last": <ts>}``
    and the public REST shape ``{"error": [...], "result": {...}}``. Empty
    ``error`` arrays are tolerated; non-empty ones raise :class:`OHLCFetchError`.

    Returns rows sorted ascending by timestamp.
    """
    if not isinstance(payload, dict):
        raise OHLCFetchError(f"OHLC payload is not a dict: {type(payload).__name__}")

    err = payload.get("error")
    if isinstance(err, list) and err:
        raise OHLCFetchError(f"Kraken OHLC error: {err}")

    # REST-shaped payloads nest data under "result"
    container: dict[str, Any] = payload
    result = payload.get("result")
    if isinstance(result, dict):
        container = result

    last_cursor_raw = container.get("last")
    last_cursor = int(last_cursor_raw) if last_cursor_raw is not None else None

    candidate_keys: list[str] = []
    if pair_hint:
        candidate_keys.append(pair_hint)
    candidate_keys.extend(
        k for k in container.keys() if k not in {"last", "error"} and k not in candidate_keys
    )

    candles_raw: list[Any] | None = None
    for key in candidate_keys:
        v = container.get(key)
        if isinstance(v, list):
            candles_raw = v
            break

    if candles_raw is None:
        return [], last_cursor

    rows: list[OHLCRow] = []
    for c in candles_raw:
        if isinstance(c, list) and len(c) >= 7:
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
        elif isinstance(c, dict):
            try:
                rows.append(
                    OHLCRow(
                        timestamp=int(c.get("timestamp") or c.get("time") or 0),
                        open=float(c.get("open") or 0),
                        high=float(c.get("high") or 0),
                        low=float(c.get("low") or 0),
                        close=float(c.get("close") or 0),
                        vwap=float(c.get("vwap") or 0),
                        volume=float(c.get("volume") or 0),
                    )
                )
            except (TypeError, ValueError):
                continue

    rows.sort(key=lambda r: r.timestamp)
    if last_cursor is None and rows:
        last_cursor = rows[-1].timestamp
    return rows, last_cursor


def default_cli_fetcher(
    pair: str,
    interval_min: int,
    since: int | None,
    *,
    asset_class: str = "tokenized_asset",
) -> dict:
    """Fetcher backed by the Kraken CLI.

    Tries the canonical pair form first (``AAPLx/USD``) and falls back to the
    compact form (``AAPLxUSD``) — same retry order as :func:`src.kraken_cli.fetch_ohlc`.
    Returns the raw JSON dict produced by ``kraken ohlc -o json``.
    """
    forms: list[str] = [pair]
    extras = candidate_pair_forms(pair)
    for f in extras:
        if f not in forms:
            forms.append(f)

    last_err: str = ""
    for form in forms:
        args = ["ohlc", form, "--interval", str(int(interval_min))]
        if asset_class:
            args.extend(["--asset-class", asset_class])
        if since is not None:
            args.extend(["--since", str(int(since))])
        result = run_cli(args)
        if result.ok and isinstance(result.stdout_json, dict):
            return result.stdout_json
        last_err = result.stderr or f"exit={result.exit_code}"
        if result.status == "missing_cli":
            break
    raise OHLCFetchError(
        f"Kraken CLI OHLC failed for {pair} (interval={interval_min}): {last_err or 'unknown error'}"
    )


def fetch_ohlc_paginated(
    pair: str,
    interval_min: int,
    target_candles: int,
    *,
    fetcher: FetcherFn | None = None,
    asset_class: str = "tokenized_asset",
    max_pages: int = 25,
    since: int | None = None,
) -> list[OHLCRow]:
    """Fetch up to ``target_candles`` rows by paginating Kraken OHLC forward.

    Each Kraken call returns at most :data:`KRAKEN_OHLC_CAP_PER_CALL` rows. We
    iterate forward in time by advancing the ``since`` parameter to the last
    timestamp of the previous batch, until one of the following stop
    conditions triggers:

    1. We reach ``target_candles`` rows.
    2. A page returns zero new rows (no progress).
    3. The ``last`` cursor is identical to the previous call's cursor (Kraken
       has no further data — we have caught up to "now" or hit the depth wall).
    4. We exhaust ``max_pages`` (defensive safety stop).

    Parameters
    ----------
    pair:
        Slash form (``"AAPLx/USD"``) — same convention as the rest of the
        code base.
    interval_min:
        Candle interval in minutes (``15``, ``60``, ``240``, ``1440``).
    target_candles:
        Desired total rows. Effective cap; we never return more than this.
    fetcher:
        Injectable callable ``(pair, interval_min, since) -> dict``. Defaults
        to :func:`default_cli_fetcher`.
    asset_class:
        Forwarded to the default fetcher only. Ignored when ``fetcher`` is
        supplied.
    max_pages:
        Hard upper bound on the number of pagination calls. Set deliberately
        low; legitimate use cases should rarely exceed 5–10 pages.
    since:
        Optional starting unix timestamp (seconds). When ``None``, the first
        call omits ``--since`` and lets Kraken serve the most recent window.

    Returns
    -------
    list[OHLCRow]
        Rows sorted ascending by timestamp, deduplicated, capped at
        ``target_candles``.

    Raises
    ------
    OHLCFetchError
        If any page returns a non-empty Kraken error array or the payload
        cannot be parsed.
    ValueError
        If ``interval_min`` or ``target_candles`` are non-positive.
    """
    if interval_min <= 0:
        raise ValueError(f"interval_min must be > 0 (got {interval_min})")
    if target_candles <= 0:
        raise ValueError(f"target_candles must be > 0 (got {target_candles})")

    if fetcher is None:
        def _bound_fetcher(p: str, i: int, s: int | None) -> dict:
            return default_cli_fetcher(p, i, s, asset_class=asset_class)
        fetcher = _bound_fetcher

    accumulated: dict[int, OHLCRow] = {}
    cursor: int | None = since
    previous_cursor: int | None = None
    pages = 0

    while pages < max_pages and len(accumulated) < target_candles:
        pages += 1
        payload = fetcher(pair, interval_min, cursor)
        rows, last_cursor = parse_ohlc_payload(payload, pair_hint=pair)

        new_count = 0
        for r in rows:
            if r.timestamp not in accumulated:
                accumulated[r.timestamp] = r
                new_count += 1

        logger.debug(
            "ohlc page %d: rows=%d new=%d total=%d cursor=%s last=%s",
            pages, len(rows), new_count, len(accumulated), cursor, last_cursor,
        )

        # Stop condition 2: no progress on this page.
        if new_count == 0:
            break
        # Stop condition 3: cursor did not advance.
        if last_cursor is not None and previous_cursor is not None and last_cursor == previous_cursor:
            break

        previous_cursor = last_cursor
        # Advance cursor for the next page. Kraken's "last" timestamp marks
        # the timestamp of the last *closed* candle; passing it back as
        # --since makes the next call return rows strictly later.
        if last_cursor is None:
            break
        cursor = last_cursor

    out = sorted(accumulated.values(), key=lambda r: r.timestamp)
    if len(out) > target_candles:
        out = out[-target_candles:]
    return out


__all__ = [
    "KRAKEN_OHLC_CAP_PER_CALL",
    "OHLCFetchError",
    "OHLCRow",
    "FetcherFn",
    "parse_ohlc_payload",
    "default_cli_fetcher",
    "fetch_ohlc_paginated",
]
