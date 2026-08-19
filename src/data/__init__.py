"""Read-only external data collectors for the research pipeline.

Subpackage :mod:`src.data.collectors` exposes venue-agnostic feeds
(DefiLlama, Wikimedia, Etherscan gas, exchange status pages) used to
**reject** hypotheses — never for live order placement.

Timestamp convention: every normalized row uses ``timestamp`` as UTC
unix seconds (int).
"""

from .collectors import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    CollectorError,
    fetch_all_status_incidents,
    fetch_chain_tvl,
    fetch_gas_oracle,
    fetch_pageviews,
    fetch_stablecoin_supply,
    fetch_status_incidents,
)

__all__ = [
    "CollectorError",
    "DEFAULT_HTTP_TIMEOUT_SECONDS",
    "fetch_all_status_incidents",
    "fetch_chain_tvl",
    "fetch_gas_oracle",
    "fetch_pageviews",
    "fetch_stablecoin_supply",
    "fetch_status_incidents",
]
