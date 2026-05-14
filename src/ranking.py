"""Per-symbol opportunity ranking.

The functions in this module are deliberately **pure**: they consume already
fetched market data (ticker / ohlc / orderbook / trades) and return a
:class:`RankedSymbol`. Network access is the caller's responsibility, which
keeps the logic trivially testable without monkey-patching ``subprocess``.

Score conventions
-----------------
- ``momentum_score`` ∈ [-1, +1] from a weighted blend of multi-horizon returns.
- ``liquidity_score`` ∈ [0, 1] from volume, trade count and spread.
- ``opportunity_score`` ∈ [-1, +1] combines the above with volatility and
  spread penalties. **Sign matters** — positive = BUY opportunity, negative =
  SELL opportunity. The dynamic universe filter ranks by absolute value so
  short-side ideas are not discarded.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional, Sequence

from .features import compute_return, compute_spread_bps, compute_volatility
from .utils import clamp, safe_float, utc_now_iso


# Targets used to map raw values into [0, 1] for the liquidity score.
_VOLUME_TARGET_24H = 5_000.0
_TRADE_COUNT_TARGET_50 = 50.0
_SPREAD_BPS_TARGET = 60.0
_VOLATILITY_15M_TARGET = 0.015


@dataclass
class RankedSymbol:
    symbol: str
    pair: str
    last_price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    spread_bps: float = 0.0
    volume_24h: float = 0.0
    trade_count_recent: int = 0
    return_5m: float = 0.0
    return_15m: float = 0.0
    return_1h: float = 0.0
    volatility_15m: float = 0.0
    volatility_1h: float = 0.0
    liquidity_score: float = 0.0
    momentum_score: float = 0.0
    spread_penalty: float = 0.0
    volatility_penalty: float = 0.0
    opportunity_score: float = 0.0
    rank: int = 0
    selected: bool = False
    skipped_reason: Optional[str] = None
    source: str = "kraken_cli"
    as_of: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


def _extract_ticker(ticker: dict | None) -> tuple[float, float, float, float]:
    if not ticker:
        return 0.0, 0.0, 0.0, 0.0
    bid = safe_float(ticker.get("bid"))
    ask = safe_float(ticker.get("ask"))
    last = safe_float(ticker.get("last")) or (bid + ask) / 2 if (bid and ask) else safe_float(ticker.get("last"))
    volume = safe_float(ticker.get("volume_24h"))
    return bid, ask, last, volume


def _extract_orderbook(orderbook: dict | None) -> tuple[float, float]:
    """Return (best_bid, best_ask) from an orderbook payload, robust to format."""
    if not orderbook:
        return 0.0, 0.0
    data = orderbook.get("data") if isinstance(orderbook, dict) else None
    if not isinstance(data, dict):
        return 0.0, 0.0
    asks = data.get("asks") or []
    bids = data.get("bids") or []
    best_ask = safe_float(asks[0][0]) if asks else 0.0
    best_bid = safe_float(bids[0][0]) if bids else 0.0
    return best_bid, best_ask


def _extract_trades_count(trades: dict | None) -> int:
    if not trades:
        return 0
    data = trades.get("data") if isinstance(trades, dict) else None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("trades", "data"):
            inner = data.get(key)
            if isinstance(inner, list):
                return len(inner)
        for value in data.values():
            if isinstance(value, list):
                return len(value)
    return 0


def _liquidity_score(volume_24h: float, trade_count: int, spread_bps: float) -> float:
    vol_norm = clamp(volume_24h / _VOLUME_TARGET_24H, 0.0, 1.0)
    tc_norm = clamp(trade_count / _TRADE_COUNT_TARGET_50, 0.0, 1.0)
    spread_norm = clamp(1.0 - spread_bps / max(_SPREAD_BPS_TARGET, 1.0), 0.0, 1.0)
    return clamp(0.45 * vol_norm + 0.35 * tc_norm + 0.20 * spread_norm, 0.0, 1.0)


def _momentum_score(r5: float, r15: float, r1h: float) -> float:
    raw = 0.5 * r1h + 0.3 * r15 + 0.2 * r5
    return clamp(raw / 0.02, -1.0, 1.0)


def _volatility_penalty(vol_15m: float) -> float:
    return clamp(vol_15m / _VOLATILITY_15M_TARGET, 0.0, 1.0)


def _spread_penalty(spread_bps: float) -> float:
    return clamp(spread_bps / (_SPREAD_BPS_TARGET * 1.5), 0.0, 1.0)


def compute_symbol_rank(
    symbol: str,
    *,
    pair: str,
    ticker: dict | None,
    candles: Sequence[dict] | None,
    orderbook: dict | None = None,
    trades: dict | None = None,
) -> RankedSymbol:
    """Compute the canonical :class:`RankedSymbol` for a single market."""
    bid, ask, last, volume = _extract_ticker(ticker)
    book_bid, book_ask = _extract_orderbook(orderbook)
    if book_bid and book_ask:
        bid = book_bid
        ask = book_ask
        last = last or (book_bid + book_ask) / 2
    spread_bps = compute_spread_bps(bid, ask)

    candles_seq = list(candles or [])
    r5 = compute_return(candles_seq, 1)            # 1h-interval candles → 1 step ≈ recent move
    r15 = compute_return(candles_seq, 1)
    r1h = compute_return(candles_seq, 1)
    if len(candles_seq) >= 4:
        r15 = compute_return(candles_seq, 1)
        r1h = compute_return(candles_seq, 4)
    vol15 = compute_volatility(candles_seq, max(4, 1))
    vol1h = compute_volatility(candles_seq, max(8, 1))

    trade_count = _extract_trades_count(trades)
    liq = _liquidity_score(volume, trade_count, spread_bps)
    mom = _momentum_score(r5, r15, r1h)
    spread_pen = _spread_penalty(spread_bps)
    vol_pen = _volatility_penalty(vol15)

    # Opportunity score: signed combination — sign follows momentum.
    opp = clamp(
        0.55 * mom
        + 0.25 * math.copysign(liq, mom if mom != 0 else 1)
        - 0.10 * spread_pen * (1 if mom >= 0 else -1)
        - 0.10 * vol_pen * (1 if mom >= 0 else -1),
        -1.0,
        1.0,
    )

    return RankedSymbol(
        symbol=symbol,
        pair=pair,
        last_price=last,
        bid=bid,
        ask=ask,
        spread_bps=spread_bps,
        volume_24h=volume,
        trade_count_recent=trade_count,
        return_5m=r5,
        return_15m=r15,
        return_1h=r1h,
        volatility_15m=vol15,
        volatility_1h=vol1h,
        liquidity_score=liq,
        momentum_score=mom,
        spread_penalty=spread_pen,
        volatility_penalty=vol_pen,
        opportunity_score=opp,
        source=str((ticker or {}).get("source", "kraken_cli")),
    )


def sort_ranking(ranked: Iterable[RankedSymbol]) -> list[RankedSymbol]:
    """Sort by absolute opportunity_score (BUY and SELL ideas mixed together)."""
    items = sorted(list(ranked), key=lambda r: abs(r.opportunity_score), reverse=True)
    for idx, item in enumerate(items, start=1):
        item.rank = idx
    return items


def apply_filters(
    ranked: Iterable[RankedSymbol],
    *,
    max_spread_bps: float,
    min_volume: float,
    min_trade_count: int,
) -> list[RankedSymbol]:
    """Annotate items with ``skipped_reason`` when they fail any filter."""
    out: list[RankedSymbol] = []
    for r in ranked:
        reason: str | None = None
        if r.last_price <= 0:
            reason = "no last_price"
        elif r.spread_bps > max_spread_bps:
            reason = f"spread {r.spread_bps:.1f}bps > {max_spread_bps}"
        elif r.volume_24h < min_volume:
            reason = f"volume {r.volume_24h:.2f} < {min_volume}"
        elif r.trade_count_recent < min_trade_count:
            reason = f"trades {r.trade_count_recent} < {min_trade_count}"
        r.skipped_reason = reason
        out.append(r)
    return out


def select_top_n(ranked: Iterable[RankedSymbol], top_n: int) -> list[RankedSymbol]:
    eligible = [r for r in ranked if r.skipped_reason is None]
    eligible_sorted = sort_ranking(eligible)
    keep = eligible_sorted[:max(0, top_n)]
    keep_set = {r.symbol for r in keep}
    for r in ranked:
        r.selected = r.symbol in keep_set
    return keep


__all__ = [
    "RankedSymbol",
    "compute_symbol_rank",
    "sort_ranking",
    "apply_filters",
    "select_top_n",
]
