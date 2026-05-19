"""Etherscan gas oracle collector (read-only).

Gas oracle (snapshot only)
--------------------------
``https://api.etherscan.io/api?module=gastracker&action=gasoracle``

The free tier accepts an optional ``apikey`` query parameter
(``ETHERSCAN_API_KEY`` env var). Without a key the endpoint may still
respond on a best-effort basis; when it does not, :func:`fetch_gas_oracle`
returns an empty sequence instead of raising so downstream research code can
degrade gracefully.

Each oracle call yields **one** normalized row:

- ``timestamp`` (int): UTC unix seconds at fetch time
- ``source`` (str): ``"etherscan_gas_oracle"``
- ``safe_gwei``, ``propose_gwei``, ``fast_gwei`` (float)
- ``has_api_key`` (bool)

Gas history (derived local cache — not from Etherscan API)
----------------------------------------------------------
Etherscan does **not** expose historical gas oracle series on the public API
used here. Daily history for event studies lives in
``data/collector_cache/etherscan_gas_history.json``, built by appending
normalized snapshot rows (see :func:`append_oracle_snapshot_to_history`).

Official on-disk schema (``etherscan_gas_history.json``)::

    {
      "source": "etherscan_gas_history",
      "entries": {
        "daily": [
          {
            "timestamp": <unix_utc_midnight_int>,
            "fast_gwei": <float_gwei>=0,
            "source": "etherscan_gas_history"
          }
        ]
      }
    }

Optional ``_meta`` / ``_disclaimer`` keys are ignored by loaders (used in
committed SYNTHETIC examples under ``data/collector_cache/examples/``).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from ._common import (
    CollectorError,
    DEFAULT_COLLECTOR_CACHE_DIR,
    default_http_fetcher,
    load_json_cache,
    save_json_cache,
    utc_now_iso,
)

ETHERSCAN_GAS_ORACLE_URL = "https://api.etherscan.io/api"
ETHERSCAN_GAS_HISTORY_SOURCE = "etherscan_gas_history"
BLOCKED_MISSING_GAS_HISTORY = "blocked: missing historical gas cache"

GasOracleFetcherFn = Callable[[Optional[str]], Any]

# Hermetic schema sample — NOT real historical gas (tests + examples only).
SYNTHETIC_GAS_HISTORY_EXAMPLE: dict[str, Any] = {
    "_meta": {
        "label": "SYNTHETIC_EXAMPLE",
        "purpose": "Unit tests and JSON schema validation only",
        "warning": (
            "NOT real Etherscan historical gas data. "
            "Never use for research conclusions or backfill."
        ),
    },
    "source": ETHERSCAN_GAS_HISTORY_SOURCE,
    "entries": {
        "daily": [
            {
                "timestamp": 1_609_459_200,
                "fast_gwei": 42.0,
                "source": ETHERSCAN_GAS_HISTORY_SOURCE,
            },
            {
                "timestamp": 1_609_545_600,
                "fast_gwei": 35.5,
                "source": ETHERSCAN_GAS_HISTORY_SOURCE,
            },
        ],
    },
}


def default_gas_oracle_fetcher(api_key: Optional[str] = None) -> Any:
    params: dict[str, str] = {"module": "gastracker", "action": "gasoracle"}
    if api_key:
        params["apikey"] = api_key
    return default_http_fetcher(ETHERSCAN_GAS_ORACLE_URL, params=params)


def parse_gas_oracle_payload(payload: Any, *, fetched_at: int | None = None) -> list[dict[str, Any]]:
    """Parse Etherscan gas oracle JSON into a one-element normalized row list."""
    if not isinstance(payload, dict):
        raise CollectorError(
            f"gas oracle payload is not a dict: {type(payload).__name__}"
        )
    status = str(payload.get("status", ""))
    message = str(payload.get("message", ""))
    result = payload.get("result")
    if status != "1" or not isinstance(result, dict):
        raise CollectorError(
            f"gas oracle error status={status!r} message={message!r}"
        )
    try:
        safe = float(result["SafeGasPrice"])
        propose = float(result["ProposeGasPrice"])
        fast = float(result["FastGasPrice"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CollectorError(f"gas oracle missing price fields: {exc}") from exc

    ts = int(fetched_at if fetched_at is not None else time.time())
    return [
        {
            "timestamp": ts,
            "source": "etherscan_gas_oracle",
            "safe_gwei": safe,
            "propose_gwei": propose,
            "fast_gwei": fast,
        }
    ]


def fetch_gas_oracle(
    cache_path: Path | None = None,
    *,
    api_key: str | None = None,
    fetcher: GasOracleFetcherFn | None = None,
    max_cache_age_seconds: int = 300,
) -> Sequence[Mapping[str, Any]]:
    """Return the current Etherscan gas oracle snapshot.

    Parameters
    ----------
    api_key:
        Optional Etherscan API key. When ``None``, reads
        ``ETHERSCAN_API_KEY`` from the environment (may be absent).
    cache_path:
        Optional JSON cache. Reused when younger than
        ``max_cache_age_seconds``.
    fetcher:
        Injectable fetcher ``(api_key) -> raw_payload``.
    max_cache_age_seconds:
        TTL for the on-disk cache (default 5 minutes).

    Returns an empty sequence when no API key is configured **and** the
    fetcher raises :class:`CollectorError` — graceful degradation for CI.
    """
    key = api_key if api_key is not None else os.environ.get("ETHERSCAN_API_KEY")
    has_key = bool(key and str(key).strip())

    if cache_path is not None:
        cached = load_json_cache(cache_path)
        row = cached.get("snapshot")
        fetched_at = cached.get("fetched_at")
        if (
            isinstance(row, dict)
            and isinstance(fetched_at, (int, float))
            and (time.time() - float(fetched_at)) <= max_cache_age_seconds
        ):
            return [row]

    f = fetcher or default_gas_oracle_fetcher
    try:
        payload = f(key if has_key else None)
    except CollectorError:
        if not has_key:
            return []
        raise

    rows = parse_gas_oracle_payload(payload)
    if rows:
        rows[0] = dict(rows[0])
        rows[0]["has_api_key"] = has_key

    if cache_path is not None and rows:
        save_json_cache(
            cache_path,
            {
                "source": "etherscan",
                "generated_at": utc_now_iso(),
                "fetched_at": rows[0]["timestamp"],
                "snapshot": rows[0],
            },
        )

    return rows


def default_etherscan_cache_path() -> Path:
    return DEFAULT_COLLECTOR_CACHE_DIR / "etherscan_gas.json"


def default_gas_history_cache_path() -> Path:
    return DEFAULT_COLLECTOR_CACHE_DIR / "etherscan_gas_history.json"


def default_gas_history_example_path() -> Path:
    return DEFAULT_COLLECTOR_CACHE_DIR / "examples" / "etherscan_gas_history.example.json"


def normalize_gas_history_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize one daily history row (midnight UTC, fast_gwei only)."""
    ts = row.get("timestamp")
    fast = row.get("fast_gwei")
    if not isinstance(ts, int):
        return None
    try:
        gwei = float(fast)
    except (TypeError, ValueError):
        return None
    if gwei < 0:
        return None
    d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
    ts_norm = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
    return {
        "timestamp": ts_norm,
        "fast_gwei": gwei,
        "source": ETHERSCAN_GAS_HISTORY_SOURCE,
    }


def load_gas_history(path: Path) -> list[dict[str, Any]]:
    """Load ``entries.daily`` from a gas history cache file."""
    raw = load_json_cache(path)
    entries = raw.get("entries") or {}
    daily = entries.get("daily") if isinstance(entries, dict) else None
    if not isinstance(daily, list):
        return []
    out: list[dict[str, Any]] = []
    for item in daily:
        if isinstance(item, dict):
            norm = normalize_gas_history_row(item)
            if norm is not None:
                out.append(norm)
    out.sort(key=lambda r: r["timestamp"])
    return out


def merge_gas_history(
    existing: Sequence[Mapping[str, Any]],
    fresh: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Union daily rows by normalized ``timestamp`` (latest row wins)."""
    by_ts: dict[int, dict[str, Any]] = {int(r["timestamp"]): dict(r) for r in existing}
    for row in fresh:
        norm = normalize_gas_history_row(row)
        if norm is not None:
            by_ts[int(norm["timestamp"])] = norm
    return [by_ts[k] for k in sorted(by_ts)]


def persist_gas_history(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Write the official ``etherscan_gas_history.json`` envelope."""
    save_json_cache(
        path,
        {
            "source": ETHERSCAN_GAS_HISTORY_SOURCE,
            "entries": {"daily": [dict(r) for r in rows]},
        },
    )


def snapshot_rows_to_daily(
    snapshot_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Convert gas-oracle snapshot rows into normalized daily history rows."""
    out: list[dict[str, Any]] = []
    for row in snapshot_rows:
        norm = normalize_gas_history_row(row)
        if norm is not None:
            out.append(norm)
    return out


def append_oracle_snapshot_to_history(
    history: Sequence[Mapping[str, Any]],
    snapshot_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge today's oracle snapshot into an existing daily history list."""
    fresh = snapshot_rows_to_daily(snapshot_rows)
    if not fresh:
        return [dict(r) for r in history]
    return merge_gas_history(history, fresh)


def resolve_gas_history(
    history_path: Path,
    *,
    use_cache_only: bool,
    snapshot_cache_path: Path | None = None,
    fetcher: GasOracleFetcherFn | None = None,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """Load (and optionally append) gas history for event-study scripts.

    Raises
    ------
    CollectorError
        With message :data:`BLOCKED_MISSING_GAS_HISTORY` when
        ``use_cache_only`` is set and ``history_path`` has no daily rows.
    """
    history = load_gas_history(history_path)
    if use_cache_only:
        if not history:
            raise CollectorError(BLOCKED_MISSING_GAS_HISTORY)
        return history

    snap_cache = snapshot_cache_path or default_etherscan_cache_path()
    try:
        snap_rows = fetch_gas_oracle(
            cache_path=snap_cache,
            fetcher=fetcher,
            api_key=api_key,
        )
        history = append_oracle_snapshot_to_history(history, snap_rows)
        persist_gas_history(history_path, history)
    except CollectorError:
        pass
    return history
