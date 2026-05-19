"""Shared helpers for read-only data collectors.

Conventions
-----------
- Every normalized row exposes ``timestamp`` as **UTC unix seconds** (int).
- Additional fields are plain JSON-serialisable scalars (str, int, float, bool).
- HTTP uses :mod:`httpx` with :data:`DEFAULT_HTTP_TIMEOUT_SECONDS`.
- Injectable ``fetcher`` callables keep unit tests hermetic (zero network).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import httpx

from ...logger import get_logger

logger = get_logger(__name__)

DEFAULT_HTTP_TIMEOUT_SECONDS = 20.0

# Default cache root (gitignored via ``data/*.json`` and ``data/collector_cache/``).
DEFAULT_COLLECTOR_CACHE_DIR = Path("data/collector_cache")


class CollectorError(RuntimeError):
    """Raised when a collector feed returns HTTP/transport or parse errors."""


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def parse_iso_date(s: str) -> Optional[date]:
    """Best-effort ISO 8601 / unix string → UTC :class:`date`."""
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def date_to_unix_start(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def date_to_unix_end(d: date) -> int:
    return int(
        datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc).timestamp()
    )


def date_in_range(ts: int, *, start: date, end: date) -> bool:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
    return start <= d <= end


def http_get_json(
    url: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> Any:
    """Perform a GET and return parsed JSON or raise :class:`CollectorError`."""
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise CollectorError(f"transport error GET {url}: {exc}") from exc
    if resp.status_code != 200:
        raise CollectorError(
            f"HTTP {resp.status_code} for {url}: {resp.text[:300]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise CollectorError(f"non-JSON response from {url}: {exc}") from exc


HttpFetcherFn = Callable[[str, Optional[Mapping[str, Any]]], Any]


def default_http_fetcher(
    url: str, params: Optional[Mapping[str, Any]] = None
) -> Any:
    return http_get_json(url, params=params)


def load_json_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("collector cache %s unreadable: %s", path, exc)
        return {}


def save_json_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:  # pragma: no cover
        logger.warning("could not persist collector cache %s: %s", path, exc)


def filter_rows_by_date_range(
    rows: list[dict[str, Any]],
    *,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        ts = row.get("timestamp")
        if not isinstance(ts, int):
            continue
        if date_in_range(ts, start=start, end=end):
            out.append(row)
    return out
