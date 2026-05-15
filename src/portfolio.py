"""Portfolio bookkeeping.

When the Kraken CLI is unavailable (or we run in pure dry-run mode), we keep a
local portfolio in SQLite. Positions are updated only by the execution layer
calling :func:`record_fill`.
"""

from __future__ import annotations

from typing import Iterable

from . import kraken_cli, market_data, storage
from .config import get_settings
from .schemas import ExecutionResult, Position, PortfolioSnapshot
from .utils import safe_float, utc_now_iso


def _market_price_for(symbol: str) -> float:
    try:
        return market_data.get_current_price(symbol)
    except Exception:  # noqa: BLE001
        return 0.0


def _empty_snapshot() -> PortfolioSnapshot:
    cfg = get_settings().config
    return PortfolioSnapshot(
        base_currency=cfg.trading.base_currency,
        cash_usd=cfg.competition.starting_equity_usd,
        positions=[],
        equity_usd=cfg.competition.starting_equity_usd,
        source="local_estimate",
    )


def load_local_snapshot() -> PortfolioSnapshot:
    cfg = get_settings().config
    rows = storage.fetch_positions()
    if not rows:
        return _empty_snapshot()
    positions: list[Position] = []
    for row in rows:
        market = _market_price_for(row["symbol"]) or row["market_price"]
        quantity = safe_float(row["quantity"])
        avg = safe_float(row["avg_entry_price"])
        notional = quantity * market
        unrealized = (market - avg) * quantity
        # ``opened_at`` is a recent addition; legacy rows may not expose it.
        opened_at = None
        try:
            opened_at = row["opened_at"]
        except (KeyError, IndexError):
            opened_at = None
        positions.append(
            Position(
                symbol=row["symbol"],
                quantity=quantity,
                avg_entry_price=avg,
                market_price=market,
                notional_usd=notional,
                unrealized_pnl_usd=unrealized,
                realized_pnl_usd=safe_float(row["realized_pnl_usd"]),
                opened_at=opened_at if isinstance(opened_at, str) and opened_at else None,
            )
        )
    cash = cfg.competition.starting_equity_usd - sum(p.quantity * p.avg_entry_price for p in positions)
    equity = cash + sum(p.notional_usd for p in positions)
    return PortfolioSnapshot(
        base_currency=cfg.trading.base_currency,
        cash_usd=cash,
        positions=positions,
        equity_usd=equity,
        source="local_estimate",
    )


def load_kraken_snapshot() -> PortfolioSnapshot | None:
    """Best-effort live snapshot from Kraken CLI. Returns None if unavailable."""
    if not kraken_cli.is_installed():
        return None
    data = kraken_cli.fetch_paper_status()
    if data.get("source") != "kraken_cli":
        return None
    payload = data.get("data") or {}
    positions_raw = payload.get("positions") or []
    positions: list[Position] = []
    for raw in positions_raw:
        if not isinstance(raw, dict):
            continue
        sym = str(raw.get("symbol") or raw.get("pair") or "")
        if not sym:
            continue
        qty = safe_float(raw.get("quantity") or raw.get("volume"))
        avg = safe_float(raw.get("avg_entry_price") or raw.get("avg_price"))
        market = _market_price_for(sym) or safe_float(raw.get("market_price")) or avg
        positions.append(
            Position(
                symbol=sym,
                quantity=qty,
                avg_entry_price=avg,
                market_price=market,
                notional_usd=qty * market,
                unrealized_pnl_usd=(market - avg) * qty,
            )
        )
    cash = safe_float(payload.get("cash_usd") or payload.get("balance"))
    equity = cash + sum(p.notional_usd for p in positions)
    return PortfolioSnapshot(
        base_currency=get_settings().config.trading.base_currency,
        cash_usd=cash,
        positions=positions,
        equity_usd=equity,
        source="kraken_cli",
    )


def get_snapshot() -> PortfolioSnapshot:
    snap = load_kraken_snapshot()
    if snap is not None:
        return snap
    return load_local_snapshot()


def get_position(symbol: str, snapshot: PortfolioSnapshot | None = None) -> Position | None:
    """Return the current ``Position`` for ``symbol`` if any.

    Used by the actionability layer to enforce SELL exit-only (no shorts) and
    to clamp SELL sizes to the actual open quantity.
    """
    snap = snapshot or get_snapshot()
    for pos in snap.positions:
        if pos.symbol == symbol and abs(pos.quantity) > 1e-9:
            return pos
    return None


def record_fill(result: ExecutionResult) -> None:
    """Apply an execution result to the local portfolio (cash + positions)."""
    if result.status not in (
        "paper_filled",
        "live_filled",
        "futures_paper_filled",
        "futures_live_filled",
        "dry_run_logged",
    ):
        return
    if result.action not in ("BUY", "SELL"):
        return
    if result.status == "dry_run_logged":
        return  # dry-run never alters the portfolio
    if not result.symbol or not result.fill_price or not result.volume:
        return

    def _row_opened_at(r) -> str | None:
        if not r:
            return None
        try:
            val = r["opened_at"]
        except (KeyError, IndexError):
            return None
        return val if isinstance(val, str) and val else None

    rows = {row["symbol"]: row for row in storage.fetch_positions()}
    existing = rows.get(result.symbol)
    quantity = safe_float(existing["quantity"]) if existing else 0.0
    avg = safe_float(existing["avg_entry_price"]) if existing else 0.0
    realized = safe_float(existing["realized_pnl_usd"]) if existing else 0.0
    prev_opened_at = _row_opened_at(existing)

    side_qty = result.volume if result.action == "BUY" else -result.volume
    new_qty = quantity + side_qty
    new_avg = avg
    new_opened_at: str | None = prev_opened_at
    if result.action == "BUY":
        if new_qty > 0:
            new_avg = (avg * quantity + result.fill_price * result.volume) / new_qty
        # New position opened: stamp opened_at if we did not already track one.
        if quantity <= 1e-9 and not prev_opened_at:
            new_opened_at = result.at or utc_now_iso()
    elif result.action == "SELL" and quantity > 0:
        realized += (result.fill_price - avg) * min(result.volume, quantity)
        if new_qty <= 1e-9:
            new_opened_at = None

    positions: list[Position] = []
    if abs(new_qty) > 1e-9:
        positions.append(
            Position(
                symbol=result.symbol,
                quantity=new_qty,
                avg_entry_price=new_avg,
                market_price=result.fill_price,
                notional_usd=new_qty * result.fill_price,
                unrealized_pnl_usd=0.0,
                realized_pnl_usd=realized,
                opened_at=new_opened_at,
            )
        )
    for sym, row in rows.items():
        if sym == result.symbol:
            continue
        positions.append(
            Position(
                symbol=sym,
                quantity=safe_float(row["quantity"]),
                avg_entry_price=safe_float(row["avg_entry_price"]),
                market_price=safe_float(row["market_price"]),
                notional_usd=safe_float(row["notional_usd"]),
                unrealized_pnl_usd=safe_float(row["unrealized_pnl_usd"]),
                realized_pnl_usd=safe_float(row["realized_pnl_usd"]),
                opened_at=_row_opened_at(row),
            )
        )
    snapshot = PortfolioSnapshot(
        base_currency=get_settings().config.trading.base_currency,
        cash_usd=0.0,
        positions=positions,
        equity_usd=sum(p.notional_usd for p in positions),
        source="local_estimate",
        as_of=utc_now_iso(),
    )
    storage.upsert_portfolio(snapshot)


__all__ = [
    "get_snapshot",
    "get_position",
    "load_local_snapshot",
    "load_kraken_snapshot",
    "record_fill",
]
