"""DefiLlama stablecoin supply and chain TVL collectors (read-only).

Sources (free, no auth)
-----------------------
- Stablecoin aggregate chart:
  ``https://stablecoins.llama.fi/stablecoincharts/all``
- Per-chain historical TVL:
  ``https://api.llama.fi/v2/historicalChainTvl/{chain}``

Normalized rows
---------------
Each row is a mapping with at least:

- ``timestamp`` (int): UTC unix seconds at day boundary
- ``source`` (str): ``"defillama_stablecoins"`` or ``"defillama_chain_tvl"``
- ``total_circulating_usd`` or ``tvl_usd`` (float)
- ``date`` (str): ``YYYY-MM-DD`` for convenience

Timestamps use the UTC midnight of each daily sample.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ._common import (
    DEFAULT_COLLECTOR_CACHE_DIR,
    CollectorError,
    default_http_fetcher,
    filter_rows_by_date_range,
    load_json_cache,
    parse_iso_date,
    save_json_cache,
    utc_now_iso,
)

STABLECOIN_CHARTS_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
CHAIN_TVL_URL_TEMPLATE = "https://api.llama.fi/v2/historicalChainTvl/{chain}"

StablecoinFetcherFn = Callable[[], Any]
ChainTvlFetcherFn = Callable[[str], Any]


def parse_stablecoin_charts(payload: Any) -> list[dict[str, Any]]:
    """Parse DefiLlama ``/stablecoincharts/all`` into normalized daily rows."""
    if not isinstance(payload, list):
        raise CollectorError(
            f"stablecoin charts payload is not a list: {type(payload).__name__}"
        )
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        ts_raw = item.get("date")
        if ts_raw is None:
            continue
        try:
            ts = int(ts_raw)
        except (TypeError, ValueError):
            continue
        # API uses unix seconds; normalize to UTC midnight of that day.
        d = datetime.fromtimestamp(ts, tz=UTC).date()
        ts_norm = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())

        circulating = item.get("totalCirculating")
        mcap: float | None = None
        if isinstance(circulating, dict):
            pegged = circulating.get("peggedUSD")
            if pegged is not None:
                try:
                    mcap = float(pegged)
                except (TypeError, ValueError):
                    mcap = None
        if mcap is None:
            # Older payloads may expose totalCirculatingUSD directly.
            raw_mcap = item.get("totalCirculatingUSD")
            if raw_mcap is not None:
                try:
                    mcap = float(raw_mcap)
                except (TypeError, ValueError):
                    continue
            else:
                continue

        rows.append(
            {
                "timestamp": ts_norm,
                "date": d.isoformat(),
                "source": "defillama_stablecoins",
                "total_circulating_usd": mcap,
                # Alias for :mod:`src.signals.stablecoin_supply` consumers.
                "total_mcap": mcap,
            }
        )
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def parse_chain_tvl(payload: Any, *, chain: str) -> list[dict[str, Any]]:
    """Parse ``/v2/historicalChainTvl/{chain}`` into normalized daily rows."""
    if not isinstance(payload, list):
        raise CollectorError(
            f"chain TVL payload is not a list: {type(payload).__name__}"
        )
    rows: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        ts_raw = item.get("date")
        tvl_raw = item.get("tvl")
        if ts_raw is None or tvl_raw is None:
            continue
        try:
            ts = int(ts_raw)
            tvl = float(tvl_raw)
        except (TypeError, ValueError):
            continue
        d = datetime.fromtimestamp(ts, tz=UTC).date()
        ts_norm = int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())
        rows.append(
            {
                "timestamp": ts_norm,
                "date": d.isoformat(),
                "source": "defillama_chain_tvl",
                "chain": str(chain),
                "tvl_usd": tvl,
            }
        )
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def default_stablecoin_fetcher() -> Any:
    return default_http_fetcher(STABLECOIN_CHARTS_URL)


def default_chain_tvl_fetcher(chain: str) -> Any:
    url = CHAIN_TVL_URL_TEMPLATE.format(chain=str(chain))
    return default_http_fetcher(url)


def fetch_stablecoin_supply(
    start_iso: str,
    end_iso: str,
    cache_path: Path | None = None,
    *,
    fetcher: StablecoinFetcherFn | None = None,
) -> Sequence[Mapping[str, Any]]:
    """Return daily stablecoin aggregate supply rows for ``[start, end]`` (inclusive).

    Parameters
    ----------
    start_iso / end_iso:
        Inclusive window (``YYYY-MM-DD`` or ISO timestamp).
    cache_path:
        Optional JSON cache file. On a full hit the network fetcher is skipped.
    fetcher:
        Injectable fetcher ``() -> raw_payload``.
    """
    start = parse_iso_date(start_iso)
    end = parse_iso_date(end_iso)
    if start is None or end is None:
        raise ValueError(
            f"could not parse start/end iso: start={start_iso!r} end={end_iso!r}"
        )
    if end < start:
        raise ValueError(f"end ({end}) < start ({start})")

    cache_key = "stablecoin_supply"
    cached_rows: list[dict[str, Any]] = []
    if cache_path is not None:
        raw_cache = load_json_cache(cache_path)
        entries = raw_cache.get("entries") or {}
        if isinstance(entries, dict) and cache_key in entries:
            cached_rows = list(entries[cache_key])
        if cached_rows and _covers_range(cached_rows, start=start, end=end):
            return filter_rows_by_date_range(cached_rows, start=start, end=end)

    f = fetcher or default_stablecoin_fetcher
    parsed = parse_stablecoin_charts(f())

    if cache_path is not None:
        merged = _merge_rows(cached_rows, parsed)
        save_json_cache(
            cache_path,
            {
                "source": "defillama",
                "generated_at": utc_now_iso(),
                "entries": {cache_key: merged},
            },
        )
        return filter_rows_by_date_range(merged, start=start, end=end)

    return filter_rows_by_date_range(parsed, start=start, end=end)


def fetch_chain_tvl(
    chain: str,
    start_iso: str,
    end_iso: str,
    cache_path: Path | None = None,
    *,
    fetcher: ChainTvlFetcherFn | None = None,
) -> Sequence[Mapping[str, Any]]:
    """Return daily chain TVL rows for ``[start, end]`` (inclusive)."""
    if not chain or not str(chain).strip():
        raise ValueError("chain must be a non-empty string")
    start = parse_iso_date(start_iso)
    end = parse_iso_date(end_iso)
    if start is None or end is None:
        raise ValueError(
            f"could not parse start/end iso: start={start_iso!r} end={end_iso!r}"
        )
    if end < start:
        raise ValueError(f"end ({end}) < start ({start})")

    cache_key = f"chain_tvl_{chain.lower()}"
    cached_rows: list[dict[str, Any]] = []
    if cache_path is not None:
        raw_cache = load_json_cache(cache_path)
        entries = raw_cache.get("entries") or {}
        if isinstance(entries, dict) and cache_key in entries:
            cached_rows = list(entries[cache_key])
        if cached_rows and _covers_range(cached_rows, start=start, end=end):
            return filter_rows_by_date_range(cached_rows, start=start, end=end)

    f = fetcher or default_chain_tvl_fetcher
    parsed = parse_chain_tvl(f(chain), chain=chain)

    if cache_path is not None:
        merged = _merge_rows(cached_rows, parsed)
        save_json_cache(
            cache_path,
            {
                "source": "defillama",
                "generated_at": utc_now_iso(),
                "entries": {cache_key: merged},
            },
        )
        return filter_rows_by_date_range(merged, start=start, end=end)

    return filter_rows_by_date_range(parsed, start=start, end=end)


def default_defillama_cache_path() -> Path:
    return DEFAULT_COLLECTOR_CACHE_DIR / "defillama.json"


def _covers_range(rows: list[dict[str, Any]], *, start: date, end: date) -> bool:
    if not rows:
        return False
    from datetime import timedelta

    needed = {(start + timedelta(days=i)) for i in range((end - start).days + 1)}
    have: set[date] = set()
    for row in rows:
        ts = row.get("timestamp")
        if isinstance(ts, int):
            have.add(datetime.fromtimestamp(ts, tz=UTC).date())
    return needed <= have


def _merge_rows(
    existing: list[dict[str, Any]], fresh: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_ts: dict[int, dict[str, Any]] = {}
    for row in existing + fresh:
        ts = row.get("timestamp")
        if isinstance(ts, int):
            by_ts[ts] = row
    return [by_ts[k] for k in sorted(by_ts)]
