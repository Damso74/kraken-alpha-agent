"""Dry-run live adapter — never calls Kraken or submits real orders (Phase 20)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.bot.orders import Order

DryRunStatus = Literal["dry_run", "blocked", "invalid"]


@dataclass(frozen=True)
class LiveOrderIntent:
    symbol: str
    side: str
    quantity: float
    notional_usd: float
    price_hint: float
    strategy: str
    reason: str


@dataclass(frozen=True)
class DryRunOrderResult:
    status: DryRunStatus
    intent: LiveOrderIntent
    message: str
    estimated_fee_usd: float = 0.0
    min_notional_usd: float = 0.0


DEFAULT_FEE_BPS = 40.0
DEFAULT_MIN_NOTIONAL_USD = 5.0


def estimate_min_notional(*, asset: str, min_eur: float = 5.0) -> float:
    """Conceptual minimum notional for micro-live budget (5–20 EUR)."""
    _ = asset
    return max(min_eur, DEFAULT_MIN_NOTIONAL_USD)


def estimate_fees(notional_usd: float, *, fee_bps: float = DEFAULT_FEE_BPS) -> float:
    return abs(notional_usd) * fee_bps / 10_000.0


def convert_paper_order_to_live_intent(order: Order, *, price: float) -> LiveOrderIntent:
    notional = order.quantity * price
    return LiveOrderIntent(
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        notional_usd=notional,
        price_hint=price,
        strategy=order.strategy,
        reason=order.reason,
    )


def validate_live_order_intent(
    intent: LiveOrderIntent,
    *,
    max_notional_usd: float = 20.0,
    allowed_assets: frozenset[str] | None = None,
) -> tuple[bool, str]:
    allowed = allowed_assets or frozenset({"BTC", "ETH"})
    sym = intent.symbol.upper().partition("/")[0]
    if sym not in allowed:
        return False, f"asset_not_allowed:{sym}"
    if intent.quantity <= 0:
        return False, "invalid_quantity"
    if intent.notional_usd > max_notional_usd + 1e-9:
        return False, f"notional_exceeds_cap:{intent.notional_usd:.2f}"
    if intent.notional_usd < estimate_min_notional(asset=sym):
        return False, "below_min_notional"
    if intent.side not in ("buy", "sell"):
        return False, "invalid_side"
    return True, "ok"


def dry_run_submit_order(
    intent: LiveOrderIntent,
    *,
    max_notional_usd: float = 20.0,
    fee_bps: float = DEFAULT_FEE_BPS,
    manual_approval: bool = False,
) -> DryRunOrderResult:
    """Simulate order submission — always dry_run, never hits venue."""
    ok, reason = validate_live_order_intent(intent, max_notional_usd=max_notional_usd)
    if not ok:
        return DryRunOrderResult(
            status="blocked",
            intent=intent,
            message=reason,
            estimated_fee_usd=estimate_fees(intent.notional_usd, fee_bps=fee_bps),
            min_notional_usd=estimate_min_notional(asset=intent.symbol),
        )
    if not manual_approval:
        return DryRunOrderResult(
            status="blocked",
            intent=intent,
            message="manual_approval_required",
            estimated_fee_usd=estimate_fees(intent.notional_usd, fee_bps=fee_bps),
        )
    return DryRunOrderResult(
        status="dry_run",
        intent=intent,
        message="dry_run_only_no_venue_call",
        estimated_fee_usd=estimate_fees(intent.notional_usd, fee_bps=fee_bps),
        min_notional_usd=estimate_min_notional(asset=intent.symbol),
    )


def intent_to_dict(intent: LiveOrderIntent) -> dict[str, Any]:
    return {
        "symbol": intent.symbol,
        "side": intent.side,
        "quantity": intent.quantity,
        "notional_usd": round(intent.notional_usd, 4),
        "price_hint": intent.price_hint,
        "strategy": intent.strategy,
        "reason": intent.reason,
    }
