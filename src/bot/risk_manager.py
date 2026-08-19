"""Paper-bot risk gate (independent of live ``src.risk``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .orders import Order

RiskVerdict = Literal["allow", "deny"]


@dataclass
class RiskConfig:
    max_position_fraction: float = 0.25
    max_total_exposure: float = 0.50
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.15
    max_trades_per_day: int = 5
    min_cash_reserve: float = 0.10


@dataclass(frozen=True)
class RiskDecision:
    verdict: RiskVerdict
    reason: str = ""
    rule: str = ""


@dataclass
class RiskState:
    """Mutable session state tracked across bars."""

    peak_equity: float = 0.0
    day_start_equity: float = 0.0
    current_day: str = ""
    trades_today: int = 0


class RiskManager:
    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()
        self.state = RiskState()

    def _day_key(self, timestamp: str | int) -> str:
        if isinstance(timestamp, int):
            return str(timestamp // 86_400)
        return str(timestamp)[:10]

    def on_bar(self, *, equity: float, timestamp: str | int) -> None:
        day = self._day_key(timestamp)
        if day != self.state.current_day:
            self.state.current_day = day
            self.state.day_start_equity = equity
            self.state.trades_today = 0
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity

    def record_trade(self) -> None:
        self.state.trades_today += 1

    def validate_order(
        self,
        order: Order,
        *,
        equity: float,
        cash_usd: float,
        position_fraction: float,
        exposure_fraction: float,
    ) -> RiskDecision:
        cfg = self.config
        if equity <= 1e-12:
            return RiskDecision("deny", "zero equity", "equity")

        if self.state.peak_equity > 1e-12:
            dd = (self.state.peak_equity - equity) / self.state.peak_equity
            if dd > cfg.max_drawdown_pct + 1e-12:
                return RiskDecision("deny", f"drawdown {dd:.4f}", "max_drawdown_pct")

        if self.state.day_start_equity > 1e-12:
            daily_loss = (self.state.day_start_equity - equity) / self.state.day_start_equity
            if daily_loss > cfg.max_daily_loss_pct + 1e-12:
                return RiskDecision("deny", f"daily_loss {daily_loss:.4f}", "max_daily_loss_pct")

        if self.state.trades_today >= cfg.max_trades_per_day:
            return RiskDecision("deny", "max trades per day", "max_trades_per_day")

        reserve = equity * cfg.min_cash_reserve
        if order.side == "buy" and cash_usd - order.quantity * order.price_hint < reserve:
            return RiskDecision("deny", "min cash reserve", "min_cash_reserve")

        projected_pos = position_fraction
        if order.side == "buy":
            add_frac = (order.quantity * order.price_hint) / equity
            projected_pos += add_frac
        if projected_pos > cfg.max_position_fraction + 1e-9:
            return RiskDecision("deny", "max position fraction", "max_position_fraction")

        projected_exp = exposure_fraction
        if order.side == "buy":
            projected_exp += (order.quantity * order.price_hint) / equity
        elif order.side == "sell":
            projected_exp -= (order.quantity * order.price_hint) / equity
        if projected_exp > cfg.max_total_exposure + 1e-9:
            return RiskDecision("deny", "max total exposure", "max_total_exposure")

        return RiskDecision("allow", "ok", "")
