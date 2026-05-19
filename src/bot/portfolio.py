"""Paper portfolio bookkeeping (no Kraken / SQLite)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .orders import Fill, Side


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    bars_held: int = 0

    @property
    def market_value(self) -> float:
        return self.quantity * self.avg_entry_price

    def mark(self, price: float) -> float:
        return self.quantity * price


@dataclass
class PaperPortfolio:
    """Cash + per-symbol positions for paper backtests."""

    cash_usd: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl_usd: float = 0.0
    fees_paid_usd: float = 0.0

    def position(self, symbol: str) -> Position:
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol)
        return self.positions[symbol]

    def apply_fill(self, fill: Fill) -> None:
        pos = self.position(fill.symbol)
        fee = fill.fee_usd
        self.fees_paid_usd += fee
        if fill.side == "buy":
            cost = fill.quantity * fill.price + fee
            if cost > self.cash_usd + 1e-9:
                raise ValueError("insufficient cash for fill")
            new_qty = pos.quantity + fill.quantity
            if new_qty > 1e-12:
                pos.avg_entry_price = (
                    (pos.quantity * pos.avg_entry_price + fill.quantity * fill.price)
                    / new_qty
                )
            pos.quantity = new_qty
            self.cash_usd -= cost
        else:
            if fill.quantity > pos.quantity + 1e-9:
                raise ValueError("cannot sell more than position")
            proceeds = fill.quantity * fill.price - fee
            pnl = (fill.price - pos.avg_entry_price) * fill.quantity - fee
            self.realized_pnl_usd += pnl
            pos.quantity -= fill.quantity
            if pos.quantity <= 1e-12:
                pos.quantity = 0.0
                pos.avg_entry_price = 0.0
                pos.bars_held = 0
            self.cash_usd += proceeds

    def mark_to_market(self, prices: Mapping[str, float]) -> dict[str, float]:
        """Return per-symbol unrealized PnL at given marks."""
        out: dict[str, float] = {}
        for sym, pos in self.positions.items():
            if pos.quantity <= 1e-12:
                continue
            mark = prices.get(sym, pos.avg_entry_price)
            out[sym] = (mark - pos.avg_entry_price) * pos.quantity
        return out

    def equity(self, prices: Mapping[str, float]) -> float:
        total = self.cash_usd
        for sym, pos in self.positions.items():
            if pos.quantity <= 1e-12:
                continue
            mark = prices.get(sym, pos.avg_entry_price)
            total += pos.quantity * mark
        return total

    def exposure_fraction(self, prices: Mapping[str, float]) -> float:
        eq = self.equity(prices)
        if eq <= 1e-12:
            return 0.0
        invested = sum(
            pos.quantity * prices.get(sym, pos.avg_entry_price)
            for sym, pos in self.positions.items()
            if pos.quantity > 1e-12
        )
        return invested / eq

    def position_fraction(self, symbol: str, prices: Mapping[str, float]) -> float:
        eq = self.equity(prices)
        if eq <= 1e-12:
            return 0.0
        pos = self.position(symbol)
        mark = prices.get(symbol, pos.avg_entry_price)
        return (pos.quantity * mark) / eq
