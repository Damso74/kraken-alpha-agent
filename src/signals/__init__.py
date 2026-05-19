"""Research-pipeline signal builders (feed rows → event timestamps).

Signals here feed :func:`src.research.event_study.run_event_study`.
They are pure, stdlib-only, and must not import execution/risk modules.

Existing production gates (Fear & Greed, BTC dominance, vol regime) live
in :mod:`src.external_signals` — do not duplicate them here.
"""

from __future__ import annotations

from .btc_mempool import build_btc_mempool_congestion_events
from .calendar_effects import (
    build_asia_session_open_events,
    build_calendar_boundary_events,
    build_us_core_session_open_events,
    build_weekend_end_events,
    build_weekend_start_events,
)
from .eth_gas_congestion import build_eth_gas_congestion_events
from .exchange_status import build_exchange_status_events
from .options_expiry import build_monthly_options_expiry_events
from .stablecoin_supply import build_stablecoin_supply_events
from .volume_shock import build_volume_shock_events
from .wiki_attention import (
    build_wiki_attention_contrarian_events,
    build_wiki_attention_momentum_events,
)

__all__ = [
    "build_stablecoin_supply_events",
    "build_wiki_attention_momentum_events",
    "build_wiki_attention_contrarian_events",
    "build_eth_gas_congestion_events",
    "build_exchange_status_events",
    "build_weekend_start_events",
    "build_weekend_end_events",
    "build_us_core_session_open_events",
    "build_asia_session_open_events",
    "build_calendar_boundary_events",
    "build_monthly_options_expiry_events",
    "build_btc_mempool_congestion_events",
    "build_volume_shock_events",
]
