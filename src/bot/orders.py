"""Order and fill types for the paper trading bot (stdlib-only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Side = Literal["buy", "sell"]
OrderStatus = Literal["pending", "filled", "rejected"]


@dataclass(frozen=True)
class Order:
    """Market order intent before risk / execution."""

    symbol: str
    side: Side
    quantity: float
    price_hint: float
    bar_index: int
    timestamp: str | int
    strategy: str
    reason: str = ""


@dataclass(frozen=True)
class Fill:
    """Executed fill after slippage and fees."""

    symbol: str
    side: Side
    quantity: float
    price: float
    fee_usd: float
    notional_usd: float
    bar_index: int
    timestamp: str | int
    strategy: str
    slippage_bps: float = 0.0
    fee_bps: float = 0.0
    order_id: str = field(default="")
