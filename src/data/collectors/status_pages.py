"""Exchange status-page incident collectors (Statuspage JSON API).

Sources (free, read-only)
-------------------------
- Kraken: ``https://status.kraken.com/api/v2/incidents.json``
- Coinbase: ``https://status.coinbase.com/api/v2/incidents.json``

Normalized rows (one per incident update / incident)
----------------------------------------------------
- ``timestamp`` (int): UTC unix seconds of ``created_at`` or ``updated_at``
- ``source`` (str): ``"statuspage_incidents"``
- ``venue`` (str): ``"kraken"`` | ``"coinbase"``
- ``incident_id`` (str)
- ``name`` (str)
- ``status`` (str): e.g. ``investigating``, ``resolved``
- ``impact`` (str): e.g. ``minor``, ``major``
- ``started_at`` / ``updated_at`` (str): ISO-8601 Z strings when present
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._common import (
    DEFAULT_COLLECTOR_CACHE_DIR,
    CollectorError,
    default_http_fetcher,
    load_json_cache,
    save_json_cache,
    utc_now_iso,
)

KRAKEN_INCIDENTS_URL = "https://status.kraken.com/api/v2/incidents.json"
COINBASE_INCIDENTS_URL = "https://status.coinbase.com/api/v2/incidents.json"

VENUE_URLS: dict[str, str] = {
    "kraken": KRAKEN_INCIDENTS_URL,
    "coinbase": COINBASE_INCIDENTS_URL,
}

IncidentsFetcherFn = Callable[[str], Any]


def default_incidents_fetcher(venue: str) -> Any:
    url = VENUE_URLS.get(venue.lower())
    if url is None:
        raise ValueError(f"unknown venue: {venue!r}")
    return default_http_fetcher(url)


def _parse_iso_timestamp(s: str) -> int | None:
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp())
    except ValueError:
        return None


def parse_statuspage_incidents(payload: Any, *, venue: str) -> list[dict[str, Any]]:
    """Parse Statuspage ``/api/v2/incidents.json`` into normalized rows."""
    if not isinstance(payload, dict):
        raise CollectorError(
            f"incidents payload is not a dict: {type(payload).__name__}"
        )
    incidents = payload.get("incidents")
    if not isinstance(incidents, list):
        raise CollectorError("incidents payload has no 'incidents' list")

    rows: list[dict[str, Any]] = []
    for inc in incidents:
        if not isinstance(inc, dict):
            continue
        inc_id = str(inc.get("id") or "")
        if not inc_id:
            continue
        name = str(inc.get("name") or "")
        status = str(inc.get("status") or "")
        impact = str(inc.get("impact") or "")
        created_at = str(inc.get("created_at") or "")
        updated_at = str(inc.get("updated_at") or created_at)
        ts = _parse_iso_timestamp(updated_at) or _parse_iso_timestamp(created_at)
        if ts is None:
            continue
        rows.append(
            {
                "timestamp": ts,
                "source": "statuspage_incidents",
                "venue": venue.lower(),
                "incident_id": inc_id,
                "name": name,
                "status": status,
                "impact": impact,
                "started_at": created_at,
                "updated_at": updated_at,
            }
        )
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def fetch_status_incidents(
    venue: str,
    cache_path: Path | None = None,
    *,
    fetcher: IncidentsFetcherFn | None = None,
) -> Sequence[Mapping[str, Any]]:
    """Return normalized incident rows for *venue* (``kraken`` or ``coinbase``)."""
    venue_key = venue.lower().strip()
    if venue_key not in VENUE_URLS:
        raise ValueError(f"venue must be one of {sorted(VENUE_URLS)}: got {venue!r}")

    cache_key = f"incidents_{venue_key}"
    if cache_path is not None and cache_path.exists():
        raw_cache = load_json_cache(cache_path)
        entries = raw_cache.get("entries") or {}
        if isinstance(entries, dict) and cache_key in entries:
            return list(entries[cache_key])

    f = fetcher or default_incidents_fetcher
    parsed = parse_statuspage_incidents(f(venue_key), venue=venue_key)

    if cache_path is not None:
        raw_cache = load_json_cache(cache_path)
        entries = dict(raw_cache.get("entries") or {})
        entries[cache_key] = parsed
        save_json_cache(
            cache_path,
            {
                "source": "statuspage",
                "generated_at": utc_now_iso(),
                "entries": entries,
            },
        )

    return parsed


def fetch_all_status_incidents(
    cache_path: Path | None = None,
    *,
    fetcher: IncidentsFetcherFn | None = None,
) -> Sequence[Mapping[str, Any]]:
    """Fetch and merge Kraken + Coinbase incident lists."""
    rows: list[dict[str, Any]] = []
    for venue in ("kraken", "coinbase"):
        rows.extend(
            fetch_status_incidents(venue, cache_path=cache_path, fetcher=fetcher)
        )
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def default_status_cache_path() -> Path:
    return DEFAULT_COLLECTOR_CACHE_DIR / "status_pages.json"
