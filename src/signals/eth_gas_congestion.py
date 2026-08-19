"""Ethereum gas congestion events (fast-track gwei z-score).

Row shape
---------
Each row is a mapping with:

- ``timestamp`` (int): unix seconds UTC
- ``fast_gwei`` (float): recommended fast gas price in gwei

Hypothesis
----------
Elevated gas prices proxy on-chain activity / NFT mints / DeFi stress;
may correlate with ETH beta and alt risk appetite.

Overfit risk
------------
Post-EIP-1559 and L2 migration shifted the level and variance of gas;
a single ``lookback`` may be non-stationary across eras.

Rejection condition
-------------------
Reject if congestion events cluster on weekends only (calendar confound)
or fail placebo tests vs random intraday anchors.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ._stats import (
    events_from_z_threshold,
    extract_float,
    rolling_z_scores,
    sort_rows_by_timestamp,
)


def build_eth_gas_congestion_events(
    rows: Sequence[Mapping[str, Any]],
    *,
    z_threshold: float = 1.5,
    lookback: int = 180,
) -> list[int]:
    """Emit timestamps when ``fast_gwei`` z-score exceeds ``z_threshold``.

    Parameters
    ----------
    rows:
        Gas oracle snapshots (see module docstring).
    z_threshold:
        Minimum z-score to flag congestion (default 1.5).
    lookback:
        Rolling reference window in observations (default 180).

    Returns
    -------
    list[int]
        Unix UTC timestamps for congestion episodes. Empty when fewer than
        ``lookback + 1`` valid gas observations exist.
    """
    if lookback < 2:
        return []
    sorted_rows = sort_rows_by_timestamp(rows)
    scored: list[Mapping[str, Any]] = []
    values: list[float] = []
    for row in sorted_rows:
        gwei = extract_float(row, "fast_gwei")
        if gwei is None or gwei < 0:
            continue
        scored.append(row)
        values.append(gwei)

    if len(values) < lookback + 1:
        return []

    z_scores = rolling_z_scores(values, lookback)
    return events_from_z_threshold(
        scored, z_scores, z_threshold=z_threshold, direction="high"
    )


__all__ = ["build_eth_gas_congestion_events"]
