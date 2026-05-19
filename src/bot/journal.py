"""Decision and trade journal for paper backtests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .orders import Fill
from .risk_manager import RiskDecision


@dataclass
class JournalEntry:
    bar_index: int
    timestamp: str | int
    symbol: str
    event: str
    details: dict[str, Any] = field(default_factory=dict)


class BotJournal:
    def __init__(self) -> None:
        self.entries: list[JournalEntry] = []
        self.trades: list[dict[str, Any]] = []

    def log_signal(
        self,
        *,
        bar_index: int,
        timestamp: str | int,
        symbol: str,
        strategy: str,
        action: str,
        reason: str,
        size_fraction: float,
    ) -> None:
        self.entries.append(
            JournalEntry(
                bar_index=bar_index,
                timestamp=timestamp,
                symbol=symbol,
                event="signal",
                details={
                    "strategy": strategy,
                    "action": action,
                    "reason": reason,
                    "size_fraction": size_fraction,
                },
            )
        )

    def log_risk(
        self,
        *,
        bar_index: int,
        timestamp: str | int,
        symbol: str,
        decision: RiskDecision,
    ) -> None:
        self.entries.append(
            JournalEntry(
                bar_index=bar_index,
                timestamp=timestamp,
                symbol=symbol,
                event="risk",
                details={"verdict": decision.verdict, "reason": decision.reason, "rule": decision.rule},
            )
        )

    def log_fill(self, fill: Fill) -> None:
        row = asdict(fill)
        self.trades.append(row)
        self.entries.append(
            JournalEntry(
                bar_index=fill.bar_index,
                timestamp=fill.timestamp,
                symbol=fill.symbol,
                event="fill",
                details=row,
            )
        )

    def log_reject(
        self,
        *,
        bar_index: int,
        timestamp: str | int,
        symbol: str,
        reason: str,
    ) -> None:
        self.entries.append(
            JournalEntry(
                bar_index=bar_index,
                timestamp=timestamp,
                symbol=symbol,
                event="reject",
                details={"reason": reason},
            )
        )

    def decisions_as_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "bar_index": e.bar_index,
                "timestamp": e.timestamp,
                "symbol": e.symbol,
                "event": e.event,
                **e.details,
            }
            for e in self.entries
        ]
