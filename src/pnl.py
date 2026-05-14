"""PnL aggregation.

The "official" PnL for the hackathon comes from Kraken via the read-only API
key. This module produces *local estimates* (clearly labelled as such) for the
dashboard and the audit bundle.
"""

from __future__ import annotations

from . import portfolio as portfolio_mod
from . import storage
from .config import get_settings
from .schemas import PnLSnapshot, PortfolioSnapshot
from .utils import safe_float, utc_now_iso


def compute_pnl(snapshot: PortfolioSnapshot | None = None) -> PnLSnapshot:
    snapshot = snapshot or portfolio_mod.get_snapshot()
    realized = sum(safe_float(p.realized_pnl_usd) for p in snapshot.positions)
    unrealized = sum(safe_float(p.unrealized_pnl_usd) for p in snapshot.positions)
    starting = get_settings().config.competition.starting_equity_usd or 0.0
    equity = snapshot.equity_usd
    drawdown_pct = 0.0
    if starting > 0 and equity > 0:
        drawdown_pct = max(0.0, (starting - equity) / starting * 100.0)
    return PnLSnapshot(
        realized_usd=realized,
        unrealized_usd=unrealized,
        net_usd=realized + unrealized,
        equity_usd=equity,
        drawdown_pct=drawdown_pct,
        source=snapshot.source,
        note=(
            "Computed locally from the agent's own fills. "
            "Official audit comes from Kraken read-only API."
            if snapshot.source == "local_estimate"
            else "Computed from Kraken CLI portfolio data."
        ),
        as_of=utc_now_iso(),
    )


def snapshot_and_persist() -> PnLSnapshot:
    snap = compute_pnl()
    storage.write_pnl(snap)
    return snap


__all__ = ["compute_pnl", "snapshot_and_persist"]
