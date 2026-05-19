"""Bitcoin mempool congestion events (vsize z-score).

Row shape
---------
Each row is a mapping with:

- ``timestamp`` (int): unix seconds UTC
- ``mempool_vsize`` (float): virtual size of the mempool in vbytes (or MB
  if the collector normalises — z-score is scale-invariant)

Hypothesis
----------
Mempool backlog signals transaction demand and fee pressure; may lead
spot/perp BTC moves on congestion spikes.

Overfit risk
------------
Fee-market structure changed after SegWit adoption and batching; level
shifts break long lookbacks.

Rejection condition
-------------------
Reject when spikes align only with known halving/news dates in-sample.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ._stats import (
    events_from_z_threshold,
    extract_float,
    rolling_z_scores,
    sort_rows_by_timestamp,
)


def build_btc_mempool_congestion_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    z_threshold: float = 1.5,
    lookback: int = 180,
) -> list[int]:
    """Emit timestamps when ``mempool_vsize`` z-score exceeds ``z_threshold``."""
    if lookback < 2:
        return []
    sorted_rows = sort_rows_by_timestamp(rows)
    scored: list[Mapping[str, Any]] = []
    values: list[float] = []
    for row in sorted_rows:
        vsize = extract_float(row, "mempool_vsize")
        if vsize is None or vsize < 0:
            continue
        scored.append(row)
        values.append(vsize)

    if len(values) < lookback + 1:
        return []

    z_scores = rolling_z_scores(values, lookback)
    return events_from_z_threshold(
        scored, z_scores, z_threshold=z_threshold, direction="high"
    )


__all__ = ["build_btc_mempool_congestion_events"]
