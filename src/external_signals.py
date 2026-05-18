"""External market-context signals for the strategy discovery sweep.

Three independent signals are exposed:

1. **Fear & Greed Index** (`fetch_fear_greed`)
   Source: https://api.alternative.me/fng/?limit=N. Free, no auth,
   daily granularity, returns an integer in ``[0, 100]`` per UTC day.

2. **BTC dominance** (`fetch_btc_dominance`)
   Source primaire: https://api.coingecko.com/api/v3/global (current
   only). Source historique: snapshot of the top-N market caps via
   /coins/markets, computed on demand. CoinGecko free has no
   authenticated historical endpoint for ``btc_dominance`` so this
   helper degrades gracefully — see docstring caveats.

3. **Realized volatility regime** (`compute_realized_vol_regime`)
   Computed locally from OHLC closes (rolling std of log-returns) and
   thresholded against the 25 / 75 quantiles of the rolling series.
   Returns ``"low"`` / ``"normal"`` / ``"high"``. No network call.

Hard safety contract
--------------------
- All three helpers are **strictly read-only**. They never import
  :mod:`src.execution`, :mod:`src.futures_kraken_cli` or any module
  that can mutate venue state.
- HTTP calls go through :mod:`httpx` with a short fixed timeout
  (``DEFAULT_HTTP_TIMEOUT_SECONDS = 20.0``) and a deterministic retry
  budget so a network flake cannot wedge the caller.
- The caches under ``data/external_cache/`` are append-only JSON
  payloads — no PnL, no decisions, no credentials. Already gitignored.
- A custom ``fetcher`` is injectable on every helper so unit tests
  exercise the parsing / caching logic without hitting the network.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

import httpx

from .logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

FEAR_GREED_URL = "https://api.alternative.me/fng/"
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"

DEFAULT_HTTP_TIMEOUT_SECONDS = 20.0
DEFAULT_FEAR_GREED_LIMIT = 365


# Type aliases for injectable fetchers (unit-test ergonomics).
FearGreedFetcherFn = Callable[[int], dict]
BtcDominanceFetcherFn = Callable[[], dict]
TopMarketsFetcherFn = Callable[[int], list]


# ---------------------------------------------------------------------------
# Fear & Greed helpers
# ---------------------------------------------------------------------------


class ExternalSignalError(RuntimeError):
    """Raised when an external feed returns a malformed payload or HTTP error."""


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_iso_date(s: str) -> Optional[date]:
    """Best-effort ISO 8601 → :class:`datetime.date` (UTC).

    The Fear & Greed payload uses a unix timestamp string. We accept
    both numeric strings and ISO date strings so the cache loader can
    handle older payloads transparently.
    """
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        # Some payloads use "YYYY-MM-DD" only.
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None


def default_fear_greed_fetcher(limit: int = DEFAULT_FEAR_GREED_LIMIT) -> dict:
    """Default HTTP fetcher: hits ``api.alternative.me`` directly."""
    params = {"limit": int(limit)}
    try:
        resp = httpx.get(
            FEAR_GREED_URL, params=params, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS
        )
    except httpx.HTTPError as exc:
        raise ExternalSignalError(
            f"transport error fetching Fear & Greed: {exc}"
        ) from exc
    if resp.status_code != 200:
        raise ExternalSignalError(
            f"Fear & Greed HTTP {resp.status_code}: {resp.text[:200]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise ExternalSignalError(
            f"Fear & Greed returned non-JSON: {exc}"
        ) from exc


def parse_fear_greed_payload(payload: Any) -> dict[date, int]:
    """Parse the Fear & Greed JSON payload into ``{utc_date: 0..100}``.

    The expected shape is ``{"data": [{"value": "53", "timestamp":
    "1700000000", ...}, ...]}``. Rows that fail to parse are silently
    dropped so a partial payload still yields usable data.
    """
    if not isinstance(payload, dict):
        raise ExternalSignalError(
            f"Fear & Greed payload is not a dict: {type(payload).__name__}"
        )
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ExternalSignalError("Fear & Greed payload has no 'data' list")
    out: dict[date, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts_raw = row.get("timestamp")
        val_raw = row.get("value")
        if ts_raw is None or val_raw is None:
            continue
        d = _parse_iso_date(str(ts_raw))
        if d is None:
            continue
        try:
            value = int(round(float(val_raw)))
        except (TypeError, ValueError):
            continue
        # Clamp to [0, 100]; the official scale never exceeds it but a
        # malformed payload should not poison the downstream gate.
        value = max(0, min(100, value))
        out[d] = value
    return out


def _date_in_range(d: date, *, start: date, end: date) -> bool:
    return start <= d <= end


def fetch_fear_greed(
    start_iso: str,
    end_iso: str,
    cache_path: Path | None = None,
    *,
    fetcher: FearGreedFetcherFn | None = None,
    limit: int = DEFAULT_FEAR_GREED_LIMIT,
) -> dict[date, int]:
    """Return ``{utc_date: 0..100}`` covering the inclusive ``[start, end]`` window.

    Parameters
    ----------
    start_iso / end_iso:
        Inclusive window in ISO 8601 (``"YYYY-MM-DD"`` or full
        timestamps). ``end < start`` raises ``ValueError``.
    cache_path:
        Optional path to a JSON cache produced by previous calls. Hit
        on cache when every date in ``[start, end]`` is present;
        otherwise falls through to ``fetcher``. ``None`` disables
        caching entirely.
    fetcher:
        Injectable HTTP fetcher (signature ``(limit) -> dict``).
        Defaults to :func:`default_fear_greed_fetcher`.
    limit:
        Number of past days to request from the API on a cache miss.
        The free endpoint accepts up to ~3 000 but anything > 365
        starts returning malformed rows, so the default is 365.
    """
    start = _parse_iso_date(start_iso)
    end = _parse_iso_date(end_iso)
    if start is None or end is None:
        raise ValueError(
            f"could not parse start/end iso: start={start_iso!r} end={end_iso!r}"
        )
    if end < start:
        raise ValueError(f"end ({end}) < start ({start})")

    cache_data: dict[date, int] = {}
    if cache_path is not None and cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            entries = raw.get("entries") or {}
            for k, v in entries.items():
                d = _parse_iso_date(str(k))
                if d is None:
                    continue
                try:
                    cache_data[d] = int(v)
                except (TypeError, ValueError):
                    continue
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "fear & greed cache %s unreadable, refreshing: %s", cache_path, exc
            )
            cache_data = {}

    if cache_data:
        # Hit only when every requested date is covered.
        covered = all(
            (start + _days(i)) in cache_data
            for i in range((end - start).days + 1)
        )
        if covered:
            logger.debug(
                "fear & greed cache hit: %s → %s (%d entries)",
                start, end, len(cache_data),
            )
            return {
                d: v for d, v in cache_data.items()
                if _date_in_range(d, start=start, end=end)
            }

    f = fetcher or default_fear_greed_fetcher
    payload = f(int(limit))
    parsed = parse_fear_greed_payload(payload)

    merged: dict[date, int] = dict(cache_data)
    merged.update(parsed)

    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "source": "alternative_me_fng",
                        "generated_at": _utc_now_iso(),
                        "entries": {
                            d.isoformat(): int(v) for d, v in sorted(merged.items())
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover (filesystem)
            logger.warning(
                "could not persist fear & greed cache to %s: %s", cache_path, exc
            )

    return {
        d: v for d, v in merged.items() if _date_in_range(d, start=start, end=end)
    }


def _days(n: int):  # tiny helper to avoid a top-level timedelta import twice
    from datetime import timedelta
    return timedelta(days=n)


# ---------------------------------------------------------------------------
# BTC dominance helpers
# ---------------------------------------------------------------------------


def default_btc_dominance_fetcher() -> dict:
    """Default fetcher hitting CoinGecko's ``/global`` endpoint.

    Returns the raw JSON dict so the parser can pick out
    ``data.market_cap_percentage.btc``.
    """
    try:
        resp = httpx.get(COINGECKO_GLOBAL_URL, timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise ExternalSignalError(
            f"transport error fetching CoinGecko /global: {exc}"
        ) from exc
    if resp.status_code != 200:
        raise ExternalSignalError(
            f"CoinGecko /global HTTP {resp.status_code}: {resp.text[:200]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise ExternalSignalError(
            f"CoinGecko /global non-JSON: {exc}"
        ) from exc


def parse_btc_dominance_global(payload: Any) -> Optional[float]:
    """Extract the **current** BTC dominance % from a ``/global`` payload.

    Returns ``None`` when the field is missing — the caller treats
    that as "no signal available" and skips the gate.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return None
    pct = data.get("market_cap_percentage") or {}
    if not isinstance(pct, dict):
        return None
    btc = pct.get("btc")
    try:
        return float(btc) if btc is not None else None
    except (TypeError, ValueError):
        return None


def default_top_markets_fetcher(per_page: int = 10) -> list:
    """Default fetcher hitting CoinGecko's ``/coins/markets`` endpoint."""
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": int(per_page),
        "page": 1,
        "sparkline": "false",
    }
    try:
        resp = httpx.get(
            COINGECKO_MARKETS_URL,
            params=params,
            timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ExternalSignalError(
            f"transport error fetching CoinGecko /coins/markets: {exc}"
        ) from exc
    if resp.status_code != 200:
        raise ExternalSignalError(
            f"CoinGecko /coins/markets HTTP {resp.status_code}: {resp.text[:200]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise ExternalSignalError(
            f"CoinGecko /coins/markets non-JSON: {exc}"
        ) from exc


def compute_btc_dominance_from_markets(markets: Sequence[Mapping[str, Any]]) -> Optional[float]:
    """Compute BTC dominance % from a top-N markets snapshot.

    The payload from ``/coins/markets`` is a list ordered by market
    cap descending. Each row exposes ``id`` and ``market_cap``; we
    sum the available caps and divide BTC's by the total.

    Returns ``None`` when BTC is missing or the total cap is zero.
    """
    if not markets:
        return None
    btc_cap: float = 0.0
    total_cap: float = 0.0
    for row in markets:
        if not isinstance(row, Mapping):
            continue
        cap = row.get("market_cap")
        if cap is None:
            continue
        try:
            cap_f = float(cap)
        except (TypeError, ValueError):
            continue
        if cap_f <= 0:
            continue
        total_cap += cap_f
        coin_id = (row.get("id") or "").lower()
        symbol = (row.get("symbol") or "").lower()
        if coin_id == "bitcoin" or symbol == "btc":
            btc_cap = cap_f
    if total_cap <= 0 or btc_cap <= 0:
        return None
    return btc_cap / total_cap * 100.0


def fetch_btc_dominance(
    start_iso: str,
    end_iso: str,
    cache_path: Path | None = None,
    *,
    global_fetcher: BtcDominanceFetcherFn | None = None,
    markets_fetcher: TopMarketsFetcherFn | None = None,
) -> dict[date, float]:
    """Return BTC dominance % per UTC day across ``[start, end]`` (inclusive).

    Caveats (intentional, surfaced in the report)
    ---------------------------------------------
    1. **CoinGecko free has no historical endpoint** for the global
       ``btc_dominance`` series. We work around this by:
       - reading every previously-cached entry,
       - querying ``/global`` for the *current* value and stamping it
         on ``end`` (so the most-recent day is always covered),
       - optionally calling ``/coins/markets`` to compute a
         top-10 snapshot dominance for the same day.

       Days in ``[start, end-1]`` that have no cached entry are
       returned as **constant** (filled with the most recent known
       value) — this is documented as a hard limitation in
       ``docs/STRATEGY_DISCOVERY_REPORT.md`` and the gate consuming
       this output is OFF by default precisely because of that.

    2. The returned mapping skips dates we cannot fill (no cache, no
       current-day fallback).

    Parameters
    ----------
    start_iso / end_iso:
        Inclusive window. Same parser as :func:`fetch_fear_greed`.
    cache_path:
        Optional JSON cache. ``None`` disables caching.
    global_fetcher / markets_fetcher:
        Injectable HTTP fetchers for unit tests.
    """
    start = _parse_iso_date(start_iso)
    end = _parse_iso_date(end_iso)
    if start is None or end is None:
        raise ValueError(
            f"could not parse start/end iso: start={start_iso!r} end={end_iso!r}"
        )
    if end < start:
        raise ValueError(f"end ({end}) < start ({start})")

    cache_data: dict[date, float] = {}
    if cache_path is not None and cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            entries = raw.get("entries") or {}
            for k, v in entries.items():
                d = _parse_iso_date(str(k))
                if d is None:
                    continue
                try:
                    cache_data[d] = float(v)
                except (TypeError, ValueError):
                    continue
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "btc dominance cache %s unreadable, refreshing: %s", cache_path, exc
            )
            cache_data = {}

    # Always pull a fresh /global snapshot so the most-recent entry is
    # current. This is a single HTTP call so it stays cheap.
    gf = global_fetcher or default_btc_dominance_fetcher
    try:
        global_payload = gf()
        current_dom = parse_btc_dominance_global(global_payload)
    except ExternalSignalError as exc:
        logger.warning("BTC dominance /global fetch failed: %s", exc)
        current_dom = None

    today_utc = datetime.now(timezone.utc).date()
    if current_dom is not None:
        cache_data[today_utc] = current_dom

    # Optional markets snapshot for today (if requested) — cross-checks
    # the /global value against a top-10 reconstruction.
    if markets_fetcher is not None:
        try:
            markets = markets_fetcher(10)
            mkt_dom = compute_btc_dominance_from_markets(markets)
            if mkt_dom is not None:
                # Only override if /global gave us nothing (otherwise
                # /global is the canonical source).
                cache_data.setdefault(today_utc, mkt_dom)
        except ExternalSignalError as exc:
            logger.warning("BTC dominance markets fetch failed: %s", exc)

    if cache_path is not None and cache_data:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "source": "coingecko_global+markets",
                        "generated_at": _utc_now_iso(),
                        "warning": (
                            "CoinGecko free has no historical btc_dominance "
                            "endpoint; entries before the latest /global "
                            "snapshot are taken from previous runs only."
                        ),
                        "entries": {
                            d.isoformat(): float(v)
                            for d, v in sorted(cache_data.items())
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover
            logger.warning(
                "could not persist btc dominance cache to %s: %s", cache_path, exc
            )

    return {
        d: v for d, v in cache_data.items() if _date_in_range(d, start=start, end=end)
    }


# ---------------------------------------------------------------------------
# Realized volatility regime
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VolRegimeBreakdown:
    """Quantile thresholds + label for the rolling realised vol of a series."""

    label: str       # "low" | "normal" | "high"
    rolling_std: float
    q25: float
    q75: float
    sample_size: int


@dataclass(frozen=True)
class ExternalSnapshot:
    """Per-decision external context bundle.

    All four fields are optional — when a fetch failed or the cache
    was incomplete we record ``None`` and the gates default to
    "pass" (no block). This way a transient network blip cannot
    silently flip the agent's behaviour.
    """

    fear_greed_index: Optional[int] = None
    btc_dominance_pct: Optional[float] = None
    btc_dominance_pct_24h_ago: Optional[float] = None
    vol_regime: Optional[str] = None  # "low" | "normal" | "high"

    @property
    def btc_dominance_change_24h_pp(self) -> Optional[float]:
        """Return the 24-hour BTC dominance change in percentage points.

        Positive = BTC dominance increased over the last 24 h (capital
        rotating into BTC). Returns ``None`` when either anchor is
        missing so the gate caller can skip cleanly.
        """
        if self.btc_dominance_pct is None or self.btc_dominance_pct_24h_ago is None:
            return None
        return float(self.btc_dominance_pct) - float(self.btc_dominance_pct_24h_ago)


def apply_external_gates(
    *,
    action: str,
    symbol: str,
    snapshot: Optional[ExternalSnapshot],
    gates: Any,
) -> Optional[str]:
    """Return a block reason string, or ``None`` if the gate passes.

    Logic:

    - All gates are **BUY-only**. ``SELL`` and ``HOLD`` always pass.
    - Each gate is independently optional. The *first* gate that
      blocks short-circuits the rest; the reason string identifies
      which gate fired so the audit log can pinpoint it.
    - When ``snapshot`` is ``None`` (no external data available) the
      gates pass with no block — a missing signal must never silently
      flip the agent into HOLD-everywhere.

    Parameters
    ----------
    action:
        The current proposed action (``"BUY" | "SELL" | "HOLD"``).
    symbol:
        Bare ticker (``"BTC"``, ``"ETH"`` ...). Only used by the
        BTC-dominance gate, which exempts ``"BTC"`` itself.
    snapshot:
        :class:`ExternalSnapshot` carrying the three signals.
    gates:
        :class:`src.config.ExternalSignalsConfig` instance (or any
        object exposing the same field names).
    """
    if action != "BUY":
        return None
    if snapshot is None or gates is None:
        return None

    fg_lt = getattr(gates, "block_buy_if_fear_greed_lt", None)
    fg_gt = getattr(gates, "block_buy_if_fear_greed_gt", None)
    btc_rising_pp = getattr(gates, "block_alt_if_btc_dominance_rising_24h_pct", None)
    vol_filter = list(getattr(gates, "vol_regime_filter", []) or [])

    fg = snapshot.fear_greed_index
    if fg_lt is not None and fg is not None and fg < int(fg_lt):
        return f"fear_greed_lt({fg}<{int(fg_lt)})"
    if fg_gt is not None and fg is not None and fg > int(fg_gt):
        return f"fear_greed_gt({fg}>{int(fg_gt)})"

    if btc_rising_pp is not None and (symbol or "").upper() != "BTC":
        delta = snapshot.btc_dominance_change_24h_pp
        if delta is not None and delta > float(btc_rising_pp):
            return (
                f"btc_dominance_rising_alt_blocked"
                f"(delta={delta:+.2f}pp>{float(btc_rising_pp):+.2f}pp)"
            )

    if vol_filter and snapshot.vol_regime is not None and snapshot.vol_regime not in vol_filter:
        return f"vol_regime_filtered({snapshot.vol_regime!r} not in {vol_filter})"

    return None


def _log_returns(closes: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev > 0 and cur > 0:
            out.append(math.log(cur / prev))
    return out


def _rolling_std(values: Sequence[float], window: int) -> list[float]:
    """Return a list of rolling sample-stdev values (length ``len(values) - window + 1``)."""
    if window < 2:
        raise ValueError(f"window must be >= 2 (got {window})")
    n = len(values)
    if n < window:
        return []
    out: list[float] = []
    for i in range(n - window + 1):
        chunk = list(values[i : i + window])
        try:
            out.append(float(statistics.stdev(chunk)))
        except statistics.StatisticsError:
            out.append(0.0)
    return out


def compute_realized_vol_regime(
    ohlc_rows: Sequence[Mapping[str, Any]] | None,
    *,
    window: int = 20,
) -> VolRegimeBreakdown:
    """Classify the most recent realised vol into ``low | normal | high``.

    The procedure is intentionally simple:

    1. Extract closes from ``ohlc_rows`` (skips rows with non-positive
       closes — same hygiene as :mod:`src.features`).
    2. Compute log-returns, then a rolling sample-stdev of width
       ``window``.
    3. Take the **last** rolling stdev (= the most recent realised vol)
       and compare it to the 25 / 75 quantiles of the whole rolling
       series.
    4. Below 25 % → ``"low"``; above 75 % → ``"high"``; in between →
       ``"normal"``.

    Returns ``"normal"`` when the input is too small to support a
    meaningful classification (the caller can then disable the
    regime-filter gate without crashing).
    """
    if not ohlc_rows:
        return VolRegimeBreakdown(
            label="normal", rolling_std=0.0, q25=0.0, q75=0.0, sample_size=0
        )
    closes = [
        float(r.get("close", 0.0))
        for r in ohlc_rows
        if isinstance(r, Mapping) and float(r.get("close", 0.0) or 0.0) > 0
    ]
    rets = _log_returns(closes)
    rolling = _rolling_std(rets, window)
    if not rolling:
        return VolRegimeBreakdown(
            label="normal",
            rolling_std=0.0,
            q25=0.0,
            q75=0.0,
            sample_size=len(rets),
        )
    last = float(rolling[-1])
    sorted_roll = sorted(rolling)
    n = len(sorted_roll)
    # Use linear interpolation for the quantiles (statistics.quantiles
    # would round to 4 cuts which is overkill here).
    def _q(p: float) -> float:
        if n == 1:
            return sorted_roll[0]
        idx = (n - 1) * p
        lo = int(math.floor(idx))
        hi = min(lo + 1, n - 1)
        weight = idx - lo
        return sorted_roll[lo] * (1.0 - weight) + sorted_roll[hi] * weight

    q25 = _q(0.25)
    q75 = _q(0.75)
    if last < q25:
        label = "low"
    elif last > q75:
        label = "high"
    else:
        label = "normal"
    return VolRegimeBreakdown(
        label=label,
        rolling_std=last,
        q25=q25,
        q75=q75,
        sample_size=n,
    )


# ---------------------------------------------------------------------------
# Convenience: pick the right value for a given timestamp
# ---------------------------------------------------------------------------


def pick_for_date(
    series: Mapping[date, Any],
    target: date,
    *,
    fallback: Any = None,
) -> Any:
    """Return ``series[target]`` falling back to the most recent prior date.

    Useful when a strategy has hourly candles but the external signal
    is daily — every candle on day ``D`` resolves to ``series[D]``,
    and if ``D`` is missing we walk backwards to the latest covered
    day.
    """
    if target in series:
        return series[target]
    earlier = [d for d in series.keys() if d <= target]
    if earlier:
        return series[max(earlier)]
    return fallback


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "FEAR_GREED_URL",
    "COINGECKO_GLOBAL_URL",
    "COINGECKO_MARKETS_URL",
    "DEFAULT_HTTP_TIMEOUT_SECONDS",
    "DEFAULT_FEAR_GREED_LIMIT",
    "ExternalSignalError",
    "FearGreedFetcherFn",
    "BtcDominanceFetcherFn",
    "TopMarketsFetcherFn",
    "VolRegimeBreakdown",
    "ExternalSnapshot",
    "apply_external_gates",
    "default_fear_greed_fetcher",
    "default_btc_dominance_fetcher",
    "default_top_markets_fetcher",
    "parse_fear_greed_payload",
    "parse_btc_dominance_global",
    "compute_btc_dominance_from_markets",
    "fetch_fear_greed",
    "fetch_btc_dominance",
    "compute_realized_vol_regime",
    "pick_for_date",
]
