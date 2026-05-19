"""Local execution simulator — slippage + fees, no venue calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .orders import Fill, Order

RejectReason = Literal[
    "zero_quantity",
    "zero_price",
    "insufficient_cash",
    "insufficient_position",
    "below_min_notional",
]


@dataclass(frozen=True)
class ExecutionConfig:
    fee_bps: float = 40.0
    slippage_bps: float = 5.0
    min_notional_usd: float = 1.0


@dataclass(frozen=True)
class SimulatedExecution:
    fill: Fill | None
    rejected: bool
    reject_reason: RejectReason | None = None


class ExecutionSimulator:
    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self.config = config or ExecutionConfig()

    def _fill_price(self, side: str, mid: float) -> float:
        slip = self.config.slippage_bps / 10_000.0
        if side == "buy":
            return mid * (1.0 + slip)
        return mid * (1.0 - slip)

    def execute_market(self, order: Order, *, cash_usd: float, position_qty: float) -> SimulatedExecution:
        cfg = self.config
        if order.quantity <= 1e-12:
            return SimulatedExecution(fill=None, rejected=True, reject_reason="zero_quantity")
        if order.price_hint <= 1e-12:
            return SimulatedExecution(fill=None, rejected=True, reject_reason="zero_price")

        px = self._fill_price(order.side, order.price_hint)
        notional = order.quantity * px
        if notional < cfg.min_notional_usd:
            return SimulatedExecution(fill=None, rejected=True, reject_reason="below_min_notional")

        fee = notional * (cfg.fee_bps / 10_000.0)
        if order.side == "buy" and notional + fee > cash_usd + 1e-9:
            return SimulatedExecution(fill=None, rejected=True, reject_reason="insufficient_cash")
        if order.side == "sell" and order.quantity > position_qty + 1e-9:
            return SimulatedExecution(fill=None, rejected=True, reject_reason="insufficient_position")

        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=px,
            fee_usd=fee,
            notional_usd=notional,
            bar_index=order.bar_index,
            timestamp=order.timestamp,
            strategy=order.strategy,
            slippage_bps=cfg.slippage_bps,
            fee_bps=cfg.fee_bps,
        )
        return SimulatedExecution(fill=fill, rejected=False)
