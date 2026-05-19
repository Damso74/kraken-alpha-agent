"""Wikipedia pageview collector via the Wikimedia Analytics REST API.

Source (free, no auth)
----------------------
``https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/``

Normalized rows
---------------
- ``timestamp`` (int): UTC unix seconds (day boundary, from ``YYYYMMDD00``)
- ``date`` (str): ``YYYY-MM-DD``
- ``source`` (str): ``"wikimedia_pageviews"``
- ``project`` (str): e.g. ``"en.wikipedia"``
- ``article`` (str): article title (spaces as underscores in URL)
- ``views`` (int): daily view count
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import httpx

from ._common import (
    CollectorError,
    DEFAULT_COLLECTOR_CACHE_DIR,
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    filter_rows_by_date_range,
    load_json_cache,
    parse_iso_date,
    save_json_cache,
    utc_now_iso,
)

# Wikimedia REST policy: descriptive User-Agent required (403 otherwise).
DEFAULT_WIKIMEDIA_USER_AGENT = (
    "KrakenAlphaAgent-Research/1.0 (read-only; contact@example.com)"
)
WIKIMEDIA_USER_AGENT_ENV = "WIKIMEDIA_USER_AGENT"
WIKIMEDIA_HTTP_TIMEOUT_SECONDS = DEFAULT_HTTP_TIMEOUT_SECONDS
WIKIMEDIA_MAX_RETRIES = 2
WIKIMEDIA_RETRY_BACKOFF_SECONDS = 0.5
_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})

PAGEVIEWS_URL_TEMPLATE = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "{project}/{access}/{agent}/{article}/daily/{start}/{end}"
)

PageviewsFetcherFn = Callable[[str, str, str, str, str, str], Any]


def resolve_wikimedia_user_agent() -> str:
    """Return User-Agent from ``WIKIMEDIA_USER_AGENT`` or project default."""
    raw = os.environ.get(WIKIMEDIA_USER_AGENT_ENV, "").strip()
    return raw if raw else DEFAULT_WIKIMEDIA_USER_AGENT


def wikimedia_request_headers() -> dict[str, str]:
    return {
        "User-Agent": resolve_wikimedia_user_agent(),
        "Accept": "application/json",
    }


def wikimedia_http_get_json(
    url: str,
    *,
    timeout: float = WIKIMEDIA_HTTP_TIMEOUT_SECONDS,
    max_retries: int = WIKIMEDIA_MAX_RETRIES,
) -> Any:
    """GET Wikimedia REST JSON with User-Agent, timeout, and light retries."""
    headers = wikimedia_request_headers()
    last_transport: httpx.HTTPError | None = None

    for attempt in range(max_retries + 1):
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            last_transport = exc
            if attempt < max_retries:
                time.sleep(WIKIMEDIA_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise CollectorError(
                f"Wikimedia transport error GET {url}: {exc}"
            ) from exc

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as exc:
                raise CollectorError(
                    f"Wikimedia non-JSON response from {url}: {exc}"
                ) from exc

        if resp.status_code == 403:
            ua = headers["User-Agent"]
            raise CollectorError(
                f"HTTP 403 Forbidden for {url} (User-Agent: {ua!r}). "
                f"Set {WIKIMEDIA_USER_AGENT_ENV} to a descriptive agent string "
                "(see https://w.wiki/4wJS): {resp.text[:300]}"
            )

        if resp.status_code in _RETRYABLE_HTTP_STATUS and attempt < max_retries:
            time.sleep(WIKIMEDIA_RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        raise CollectorError(
            f"HTTP {resp.status_code} for {url}: {resp.text[:300]}"
        )

    raise CollectorError(
        f"Wikimedia GET failed for {url}: {last_transport}"
    )


def _format_wikimedia_day(d: date) -> str:
    """Wikimedia expects ``YYYYMMDD00`` (start) or ``YYYYMMDD23`` (end)."""
    return d.strftime("%Y%m%d")


def build_pageviews_url(
    *,
    project: str = "en.wikipedia",
    article: str = "Bitcoin",
    access: str = "all-access",
    agent: str = "all-agents",
    start: date,
    end: date,
) -> str:
    start_s = _format_wikimedia_day(start) + "00"
    end_s = _format_wikimedia_day(end) + "23"
    # Article path segment: spaces → underscores, no leading slash.
    article_seg = article.replace(" ", "_")
    return PAGEVIEWS_URL_TEMPLATE.format(
        project=project,
        access=access,
        agent=agent,
        article=article_seg,
        start=start_s,
        end=end_s,
    )


def default_pageviews_fetcher(
    project: str,
    article: str,
    access: str,
    agent: str,
    start_iso: str,
    end_iso: str,
) -> Any:
    start = parse_iso_date(start_iso)
    end = parse_iso_date(end_iso)
    if start is None or end is None:
        raise ValueError(f"invalid iso window: {start_iso!r} {end_iso!r}")
    url = build_pageviews_url(
        project=project,
        article=article,
        access=access,
        agent=agent,
        start=start,
        end=end,
    )
    return wikimedia_http_get_json(url)


def parse_pageviews_payload(
    payload: Any,
    *,
    project: str,
    article: str,
) -> list[dict[str, Any]]:
    """Parse Wikimedia pageviews JSON into normalized daily rows."""
    if not isinstance(payload, dict):
        raise CollectorError(
            f"pageviews payload is not a dict: {type(payload).__name__}"
        )
    items = payload.get("items")
    if not isinstance(items, list):
        raise CollectorError("pageviews payload has no 'items' list")
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ts_raw = item.get("timestamp")
        views_raw = item.get("views")
        if ts_raw is None or views_raw is None:
            continue
        ts_str = str(ts_raw)
        if len(ts_str) < 8 or not ts_str[:8].isdigit():
            continue
        try:
            d = date(int(ts_str[0:4]), int(ts_str[4:6]), int(ts_str[6:8]))
            views = int(views_raw)
        except (TypeError, ValueError):
            continue
        ts_norm = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
        rows.append(
            {
                "timestamp": ts_norm,
                "date": d.isoformat(),
                "source": "wikimedia_pageviews",
                "project": project,
                "article": article,
                "views": views,
            }
        )
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def fetch_pageviews(
    article: str,
    start_iso: str,
    end_iso: str,
    cache_path: Path | None = None,
    *,
    project: str = "en.wikipedia",
    access: str = "all-access",
    agent: str = "all-agents",
    fetcher: PageviewsFetcherFn | None = None,
) -> Sequence[Mapping[str, Any]]:
    """Return daily Wikipedia pageview rows for ``[start, end]`` (inclusive)."""
    start = parse_iso_date(start_iso)
    end = parse_iso_date(end_iso)
    if start is None or end is None:
        raise ValueError(
            f"could not parse start/end iso: start={start_iso!r} end={end_iso!r}"
        )
    if end < start:
        raise ValueError(f"end ({end}) < start ({start})")

    cache_key = f"pageviews_{project}_{article}".replace(" ", "_")
    cached_rows: list[dict[str, Any]] = []
    if cache_path is not None:
        raw_cache = load_json_cache(cache_path)
        entries = raw_cache.get("entries") or {}
        if isinstance(entries, dict) and cache_key in entries:
            cached_rows = list(entries[cache_key])
        if cached_rows and _covers_range(cached_rows, start=start, end=end):
            return filter_rows_by_date_range(cached_rows, start=start, end=end)

    f = fetcher or default_pageviews_fetcher
    payload = f(project, article, access, agent, start_iso, end_iso)
    parsed = parse_pageviews_payload(payload, project=project, article=article)

    if cache_path is not None:
        merged = _merge_rows(cached_rows, parsed)
        save_json_cache(
            cache_path,
            {
                "source": "wikimedia",
                "generated_at": utc_now_iso(),
                "entries": {cache_key: merged},
            },
        )
        return filter_rows_by_date_range(merged, start=start, end=end)

    return filter_rows_by_date_range(parsed, start=start, end=end)


def default_wikimedia_cache_path() -> Path:
    return DEFAULT_COLLECTOR_CACHE_DIR / "wikimedia.json"


def _covers_range(rows: list[dict[str, Any]], *, start: date, end: date) -> bool:
    if not rows:
        return False
    needed = {(start + timedelta(days=i)) for i in range((end - start).days + 1)}
    have: set[date] = set()
    for row in rows:
        ts = row.get("timestamp")
        if isinstance(ts, int):
            have.add(datetime.fromtimestamp(ts, tz=timezone.utc).date())
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
