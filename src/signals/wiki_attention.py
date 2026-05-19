"""Wikipedia pageview attention shock events (rolling z-score).

Row shape
---------
Each row is a mapping with:

- ``timestamp`` (int): unix seconds UTC
- ``pageviews`` (float): views in the aggregation window (daily typical)
- ``article`` (str): article title (used for basket grouping)

Hypothesis
----------
- **Momentum**: abnormal attention spikes predict continued interest and
  short-horizon volatility / volume in related assets (return is secondary).
- **Basket**: aggregate crypto-topic attention may be more stable than a
  single flagship article (Bitcoin-only Phase 6 was weak).

Overfit risk
------------
Article selection and lookback interact strongly; Wikipedia traffic has
structural breaks (mobile app changes, bot filtering). Thresholds are
pre-registered only (1.5 and 2.0) — no post-hoc tuning.

Rejection condition
-------------------
Discard when event-study vol/volume effects are not robust vs shift +30d,
random-event bootstrap, and non-crypto page placebos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ._stats import (
    events_from_z_threshold,
    extract_float,
    extract_timestamp,
    rolling_z_scores,
    sort_rows_by_timestamp,
)

# Phase 11 crypto attention basket (fixed; not optimized post-hoc).
CRYPTO_ATTENTION_BASKET: tuple[str, ...] = (
    "Bitcoin",
    "Ethereum",
    "Solana",
    "Tether",
    "USD Coin",
    "Coinbase",
    "Cryptocurrency",
    "Cryptocurrency exchange",
)

# Non-crypto pages for falsification (same machinery, should not predict BTC).
NON_CRYPTO_PLACEBO_BASKET: tuple[str, ...] = (
    "United States",
    "World War II",
    "Barack Obama",
    "Summer Olympic Games",
)

# Pre-registered z thresholds only (no additional grid search).
PREREGISTERED_Z_THRESHOLDS: tuple[float, ...] = (1.5, 2.0)

BASKET_AGGREGATE_ARTICLE = "__basket_aggregate__"


def _pageview_values(rows: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], list[float]]:
    scored: list[Mapping[str, Any]] = []
    values: list[float] = []
    for row in rows:
        pv = extract_float(row, "pageviews")
        if pv is None or pv < 0:
            continue
        scored.append(row)
        values.append(pv)
    return scored, values


def group_rows_by_article(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    """Bucket rows by ``article`` field (missing → ``""``)."""
    out: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        art = str(row.get("article") or "").strip()
        out.setdefault(art, []).append(row)
    for art in out:
        out[art] = sort_rows_by_timestamp(out[art])
    return out


def build_wiki_basket_aggregate_rows(
    rows_by_article: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    articles: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Sum daily pageviews across ``articles`` into one synthetic series."""
    names = tuple(articles) if articles is not None else CRYPTO_ATTENTION_BASKET
    by_ts: dict[int, float] = {}
    for name in names:
        for row in rows_by_article.get(name, ()):
            ts = extract_timestamp(row)
            pv = extract_float(row, "pageviews")
            if ts is None or pv is None:
                continue
            by_ts[ts] = by_ts.get(ts, 0.0) + pv
    return [
        {
            "timestamp": ts,
            "pageviews": total,
            "article": BASKET_AGGREGATE_ARTICLE,
        }
        for ts, total in sorted(by_ts.items())
    ]


def build_wiki_attention_momentum_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    z_threshold: float = 2.0,
    lookback: int = 30,
) -> list[int]:
    """Positive pageview z-score spikes (momentum / attention surge).

    Fires when ``z > z_threshold`` on ``pageviews``.
    """
    if lookback < 2:
        return []
    sorted_rows = sort_rows_by_timestamp(rows)
    scored, values = _pageview_values(sorted_rows)
    if len(values) < lookback + 1:
        return []
    z_scores = rolling_z_scores(values, lookback)
    return events_from_z_threshold(
        scored, z_scores, z_threshold=z_threshold, direction="high"
    )


def build_wiki_attention_contrarian_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    z_threshold: float = 2.0,
    lookback: int = 30,
) -> list[int]:
    """Abnormally *low* pageview z-scores (contrarian / attention vacuum).

    Fires when ``z < -z_threshold`` — unusually quiet periods that may
    precede mean reversion in sentiment-linked assets.
    """
    if lookback < 2:
        return []
    sorted_rows = sort_rows_by_timestamp(rows)
    scored, values = _pageview_values(sorted_rows)
    if len(values) < lookback + 1:
        return []
    z_scores = rolling_z_scores(values, lookback)
    return events_from_z_threshold(
        scored, z_scores, z_threshold=z_threshold, direction="low"
    )


@dataclass(frozen=True)
class WikiBasketEvents:
    """Page-level and aggregate basket momentum events at one threshold."""

    z_threshold: float
    per_page: dict[str, tuple[int, ...]]
    basket_aggregate: tuple[int, ...]


def build_wiki_basket_momentum_events(
    rows_by_article: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    z_threshold: float,
    lookback: int = 30,
    articles: Sequence[str] | None = None,
) -> WikiBasketEvents:
    """Build per-page and summed-basket momentum events (basket mode)."""
    names = tuple(articles) if articles is not None else CRYPTO_ATTENTION_BASKET
    per_page: dict[str, tuple[int, ...]] = {}
    for name in names:
        page_rows = list(rows_by_article.get(name, ()))
        ev = build_wiki_attention_momentum_events(
            page_rows,
            z_threshold=z_threshold,
            lookback=lookback,
        )
        per_page[name] = tuple(ev)
    agg_rows = build_wiki_basket_aggregate_rows(rows_by_article, articles=names)
    basket_ev = build_wiki_attention_momentum_events(
        agg_rows,
        z_threshold=z_threshold,
        lookback=lookback,
    )
    return WikiBasketEvents(
        z_threshold=z_threshold,
        per_page=per_page,
        basket_aggregate=tuple(basket_ev),
    )


def build_preregistered_basket_momentum_events(
    rows_by_article: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    lookback: int = 30,
    articles: Sequence[str] | None = None,
) -> dict[float, WikiBasketEvents]:
    """Return basket events for each pre-registered ``z_threshold``."""
    return {
        z: build_wiki_basket_momentum_events(
            rows_by_article,
            z_threshold=z,
            lookback=lookback,
            articles=articles,
        )
        for z in PREREGISTERED_Z_THRESHOLDS
    }


__all__ = [
    "BASKET_AGGREGATE_ARTICLE",
    "CRYPTO_ATTENTION_BASKET",
    "NON_CRYPTO_PLACEBO_BASKET",
    "PREREGISTERED_Z_THRESHOLDS",
    "WikiBasketEvents",
    "build_preregistered_basket_momentum_events",
    "build_wiki_attention_contrarian_events",
    "build_wiki_attention_momentum_events",
    "build_wiki_basket_aggregate_rows",
    "build_wiki_basket_momentum_events",
    "group_rows_by_article",
]
