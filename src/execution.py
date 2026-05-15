"""Execution layer.

Three modes:

- ``dry_run``: log the intent only. Default, used everywhere unless explicitly
  flipped. Never reaches the Kraken CLI.
- ``paper``: paper-trade through the Kraken CLI when installed; otherwise
  return a clearly labelled simulated fill so the dashboard shows something.
- ``live``: real money. Requires the triple opt-in
  (TRADING_MODE=live, LIVE_TRADING=true, ALLOW_LIVE_ORDERS=true). The risk
  module is the single source of truth for the triple-gate check; this module
  re-validates it as a belt-and-suspenders safety net.
"""

from __future__ import annotations

import time
from typing import Any

from . import futures_kraken_cli, kraken_cli, portfolio
from .config import get_settings
from .logger import get_logger
from .schemas import (
    Decision,
    EnsembleResult,
    ExecutionResult,
    Features,
    RiskResult,
)
from .universe import normalize_symbol
from .utils import new_id, safe_float

logger = get_logger(__name__)

# 30-second cache for the paper-status probe so we do not hammer the CLI
# at every cycle. Tests reset this via `reset_paper_init_cache()`.
_PAPER_INIT_CACHE: dict[str, float | bool | None] = {
    "checked_at": 0.0,
    "initialised": None,
}
_PAPER_INIT_TTL_SECONDS = 30.0


def reset_paper_init_cache() -> None:
    _PAPER_INIT_CACHE["checked_at"] = 0.0
    _PAPER_INIT_CACHE["initialised"] = None


def _paper_initialised_cached() -> bool:
    now = time.time()
    last = float(_PAPER_INIT_CACHE.get("checked_at") or 0.0)
    cached = _PAPER_INIT_CACHE.get("initialised")
    if cached is not None and (now - last) < _PAPER_INIT_TTL_SECONDS:
        return bool(cached)
    try:
        status = kraken_cli.fetch_paper_status()
    except Exception:  # noqa: BLE001
        status = None
    initialised = False
    if isinstance(status, dict) and not status.get("using_mock"):
        data = status.get("data") or {}
        if isinstance(data, dict):
            initialised = any(k in data for k in ("balance", "balances", "cash", "equity"))
    _PAPER_INIT_CACHE["checked_at"] = now
    _PAPER_INIT_CACHE["initialised"] = initialised
    return initialised


def _build_blocked(
    *,
    mode: str,
    features: Features,
    ensemble: EnsembleResult,
    reason: str,
) -> ExecutionResult:
    return ExecutionResult(
        status="blocked",
        mode=mode,  # type: ignore[arg-type]
        symbol=features.symbol,
        action=ensemble.action,
        requested_size_usd=ensemble.suggested_size_usd,
        error=reason,
    )


def _simulate_paper_fill(
    *, features: Features, ensemble: EnsembleResult, size_usd: float, note: str
) -> ExecutionResult:
    price = max(features.last_price, 0.01)
    volume = size_usd / price
    return ExecutionResult(
        status="paper_filled",
        mode="paper",
        order_id=new_id("paper"),
        symbol=features.symbol,
        action=ensemble.action,
        requested_size_usd=size_usd,
        filled_size_usd=size_usd,
        fill_price=price,
        volume=volume,
        fee=size_usd * 0.001,
        raw={"simulated": True, "note": note},
    )


def _futures_size_contracts(size_usd: float, mark_price: float) -> float:
    """Convert a USD notional to a futures contract size.

    All xStocks Perps confirmed on 2026-05-15 use ``contractSize=1`` (one
    contract = one underlying share, priced in USD). The Kraken Futures
    venue enforces ``contractValueTradePrecision`` per instrument (2 for
    most xStocks names, 3 for SPYx/QQQx/GLDx). Rounding to 4 decimals as
    we used to do produces sizes like ``0.0649`` that the venue rejects
    with ``status:invalidSize``. Round to **2 decimals** so the result
    is always a valid multiple of the most restrictive precision (and
    still a valid multiple of precision=3, since 0.01 is a multiple of
    0.001).
    """

    px = max(float(mark_price or 0.0), 0.01)
    return round(max(float(size_usd), 0.0) / px, 2)


def _execute_futures(
    *,
    mode: str,
    features: Features,
    ensemble: EnsembleResult,
    size_usd: float,
    open_long_qty: float,
) -> ExecutionResult:
    """Route an order through the Kraken Futures Perpetual engine.

    Hard guarantees:

    * Leverage flag is forced to ``1.0`` at the wrapper. The risk gate has
      already refused anything else upstream — this is the second barrier.
    * SELL is reduce-only and clamped to the open long quantity. Without an
      open long the order is blocked.
    * The order payload is logged with ``cli_ord_id``, USD notional, mark
      price and ``mode: "futures_perp_1x"`` so the audit trail differentiates
      futures fills from legacy spot rows.
    """

    sym_spot = features.symbol
    futures_symbol = futures_kraken_cli.to_futures_symbol(sym_spot)
    if futures_symbol is None:
        return _build_blocked(
            mode=mode, features=features, ensemble=ensemble,
            reason=f"no futures listing for {sym_spot} (xStocks Perp universe)",
        )

    mark_price = float(getattr(features, "mark_price", None) or features.last_price or 0.0)
    if mark_price <= 0.0:
        return _build_blocked(
            mode=mode, features=features, ensemble=ensemble,
            reason="mark price unavailable for futures sizing",
        )

    # Kraken Futures rejects very small orders with status:invalidSize. The
    # actual venue minimum on xStocks Perps depends on the per-instrument
    # tick (typically 0.1 contract on small-name names, 0.01 on liquid ones).
    # To be safe we floor BUY notionals to the per-position cap (or the
    # configured floor below it) so we always submit at least one
    # acceptable contract count. SELL is left untouched so reduce-only
    # flatten still works on tiny dust positions.
    MIN_FUTURES_BUY_NOTIONAL_USD = 25.0
    if ensemble.action == "BUY" and 0.0 < size_usd < MIN_FUTURES_BUY_NOTIONAL_USD:
        cap = float(get_settings().config.risk.max_position_notional_usd or 0.0)
        floor = min(MIN_FUTURES_BUY_NOTIONAL_USD, cap) if cap > 0 else MIN_FUTURES_BUY_NOTIONAL_USD
        if size_usd < floor:
            size_usd = floor

    contracts = _futures_size_contracts(size_usd, mark_price)
    if contracts <= 0:
        return ExecutionResult(
            status="skipped",
            mode=mode,  # type: ignore[arg-type]
            symbol=features.symbol, action=ensemble.action,
            requested_size_usd=0.0,
        )

    # SELL is exit-only on futures. Clamp the contract count to the open
    # long quantity; refuse the order when no long exists.
    reduce_only = False
    if ensemble.action == "SELL":
        if open_long_qty <= 1e-9:
            return _build_blocked(
                mode=mode, features=features, ensemble=ensemble,
                reason="SELL without open long (futures engine refuses to open shorts)",
            )
        contracts = min(contracts, round(open_long_qty, 4))
        reduce_only = True

    cli_ord_id = new_id("fut")

    if mode == "dry_run":
        return ExecutionResult(
            status="dry_run_logged",
            mode="dry_run",
            order_id=cli_ord_id,
            symbol=features.symbol, action=ensemble.action,
            requested_size_usd=size_usd, filled_size_usd=size_usd,
            fill_price=mark_price, volume=contracts,
            raw={
                "engine": "futures",
                "mode": "futures_perp_1x",
                "futures_symbol": futures_symbol,
                "cli_ord_id": cli_ord_id,
                "mark_price": mark_price,
                "notional_usd": size_usd,
                "reduce_only": reduce_only,
                "leverage": 1.0,
                "note": "dry_run — no order leaves the process",
            },
        )

    if mode == "paper":
        result = futures_kraken_cli.place_paper_order(
            side=ensemble.action,  # type: ignore[arg-type]
            symbol=futures_symbol, size=contracts,
            order_type="market", leverage=1.0,
            reduce_only=reduce_only, client_order_id=cli_ord_id,
        )
        if not result.ok:
            return ExecutionResult(
                status="futures_failed",
                mode="paper",
                symbol=features.symbol, action=ensemble.action,
                requested_size_usd=size_usd,
                error=f"kraken futures paper {ensemble.action.lower()} failed: {result.stderr[:200]}",
                raw={
                    "engine": "futures",
                    "mode": "futures_perp_1x",
                    "futures_symbol": futures_symbol,
                    "cli_ord_id": cli_ord_id,
                    "mark_price": mark_price,
                    "leverage": 1.0,
                    "cli": result.__dict__,
                },
            )
        payload = result.stdout_json if isinstance(result.stdout_json, dict) else {}
        return ExecutionResult(
            status="futures_paper_filled",
            mode="paper",
            order_id=str(payload.get("order_id") or cli_ord_id),
            symbol=features.symbol, action=ensemble.action,
            requested_size_usd=size_usd,
            filled_size_usd=safe_float(payload.get("cost"), size_usd),
            fill_price=safe_float(payload.get("price"), mark_price),
            volume=safe_float(payload.get("size") or payload.get("volume"), contracts),
            fee=safe_float(payload.get("fee"), 0.0),
            raw={
                "engine": "futures",
                "mode": "futures_perp_1x",
                "futures_symbol": futures_symbol,
                "cli_ord_id": cli_ord_id,
                "mark_price": mark_price,
                "leverage": 1.0,
                "reduce_only": reduce_only,
                "payload": payload,
            },
        )

    # mode == "live"
    s = get_settings()
    if not s.all_live_flags_on():
        return _build_blocked(
            mode="live", features=features, ensemble=ensemble,
            reason="live trading not enabled (triple opt-in missing)",
        )

    # Validate-only first — kraken futures order has no native --validate,
    # so we use the paper engine as a structural sanity check. The risk
    # gate has already approved the trade, and the paper run uses real
    # market data so any market-side rejection (post-only, suspended,
    # tick mismatch) surfaces here without risking mainnet collateral.
    exec_cfg = s.config.execution
    if exec_cfg.require_validate_first:
        v = futures_kraken_cli.validate_via_paper(
            side=ensemble.action,  # type: ignore[arg-type]
            symbol=futures_symbol, size=max(contracts, 0.0001),
            client_order_id=f"{cli_ord_id}-v",
        )
        if not v.ok:
            return ExecutionResult(
                status="futures_failed",
                mode="live",
                symbol=features.symbol, action=ensemble.action,
                requested_size_usd=size_usd,
                error=f"futures validate (via paper) failed: {v.stderr[:200]}",
                raw={
                    "engine": "futures",
                    "mode": "futures_perp_1x",
                    "futures_symbol": futures_symbol,
                    "cli_ord_id": cli_ord_id,
                    "validate": v.__dict__,
                },
            )

    result = futures_kraken_cli.place_live_order(
        side=ensemble.action,  # type: ignore[arg-type]
        symbol=futures_symbol, size=contracts,
        order_type="market", reduce_only=reduce_only,
        client_order_id=cli_ord_id,
    )
    if not result.ok:
        return ExecutionResult(
            status="futures_failed",
            mode="live",
            symbol=features.symbol, action=ensemble.action,
            requested_size_usd=size_usd,
            error=f"futures live order failed: {result.stderr[:200]}",
            raw={
                "engine": "futures",
                "mode": "futures_perp_1x",
                "futures_symbol": futures_symbol,
                "cli_ord_id": cli_ord_id,
                "mark_price": mark_price,
                "leverage": 1.0,
                "reduce_only": reduce_only,
                "cli": result.__dict__,
            },
        )
    payload = result.stdout_json if isinstance(result.stdout_json, dict) else {}
    logger.info(
        "futures_perp_1x %s %s contracts=%.4f notional=%.2fUSD mark=%.4f cli_ord_id=%s",
        ensemble.action, futures_symbol, contracts, size_usd, mark_price, cli_ord_id,
    )
    return ExecutionResult(
        status="futures_live_filled",
        mode="live",
        order_id=str(payload.get("order_id") or cli_ord_id),
        symbol=features.symbol, action=ensemble.action,
        requested_size_usd=size_usd,
        filled_size_usd=safe_float(payload.get("cost"), size_usd),
        fill_price=safe_float(payload.get("price"), mark_price),
        volume=safe_float(payload.get("size") or payload.get("volume"), contracts),
        fee=safe_float(payload.get("fee"), 0.0),
        raw={
            "engine": "futures",
            "mode": "futures_perp_1x",
            "futures_symbol": futures_symbol,
            "cli_ord_id": cli_ord_id,
            "mark_price": mark_price,
            "leverage": 1.0,
            "reduce_only": reduce_only,
            "payload": payload,
        },
    )


def execute(
    *,
    features: Features,
    ensemble: EnsembleResult,
    risk: RiskResult,
) -> ExecutionResult:
    s = get_settings()
    mode = (s.env.trading_mode or "dry_run").lower()
    exec_cfg = s.config.execution
    engine = (exec_cfg.engine or "spot").lower()

    if not risk.approved:
        return _build_blocked(
            mode=mode,
            features=features,
            ensemble=ensemble,
            reason="; ".join(risk.reasons) or "risk manager refused",
        )

    if ensemble.action == "HOLD":
        return ExecutionResult(
            status="skipped",
            mode=mode,  # type: ignore[arg-type]
            symbol=features.symbol,
            action="HOLD",
            requested_size_usd=0.0,
        )

    # Final size after the risk manager has clamped it.
    size_usd = max(risk.adjusted_size_usd or ensemble.suggested_size_usd, 0.0)

    # ----- Futures engine branch ------------------------------------------
    if engine == "futures":
        # Resolve current open long for the symbol so SELL can be clamped
        # to a reduce-only fill (never opens a short, per intransigeant
        # safeguards).
        try:
            snapshot = portfolio.get_snapshot()
            open_pos = portfolio.get_position(features.symbol, snapshot=snapshot)
            open_long_qty = float(open_pos.quantity) if (open_pos and open_pos.quantity > 0) else 0.0
        except Exception:  # noqa: BLE001
            open_long_qty = 0.0
        return _execute_futures(
            mode=mode,
            features=features,
            ensemble=ensemble,
            size_usd=size_usd,
            open_long_qty=open_long_qty,
        )

    if mode == "dry_run":
        return ExecutionResult(
            status="dry_run_logged",
            mode="dry_run",
            order_id=new_id("dry"),
            symbol=features.symbol,
            action=ensemble.action,
            requested_size_usd=size_usd,
            filled_size_usd=size_usd,
            fill_price=features.last_price,
            volume=size_usd / max(features.last_price, 0.01),
            raw={"note": "dry_run — no order leaves the process"},
        )

    sym = normalize_symbol(features.symbol)
    if mode == "paper":
        size_usd = min(size_usd, exec_cfg.paper_size_usd)
        volume = size_usd / max(features.last_price, 0.01)
        if not kraken_cli.is_installed():
            return _simulate_paper_fill(
                features=features,
                ensemble=ensemble,
                size_usd=size_usd,
                note="kraken cli not installed — simulated fill",
            )
        # Paper init guard: never call `paper buy/sell` against an
        # uninitialised account. The user must run
        # `kraken paper init` (or `python scripts/paper_smoke_test.py --init`)
        # exactly once before paper mode can produce fills.
        if not _paper_initialised_cached():
            return ExecutionResult(
                status="blocked_paper_not_initialized",
                mode="paper",
                symbol=features.symbol,
                action=ensemble.action,
                requested_size_usd=size_usd,
                error=(
                    "paper account not initialised — run "
                    "`kraken paper init --balance 10000 --currency USD --yes` "
                    "or `python scripts/paper_smoke_test.py --init`"
                ),
            )
        cli_result = kraken_cli.place_order(
            mode="paper",
            symbol_pair=sym.pair_slash,
            action=ensemble.action,
            volume=round(volume, 6),
        )
        if not cli_result.ok:
            # Fall back to deterministic simulation so the loop never dies in
            # paper mode.
            return _simulate_paper_fill(
                features=features,
                ensemble=ensemble,
                size_usd=size_usd,
                note=f"kraken cli paper failed: {cli_result.stderr[:140]}",
            )
        payload = cli_result.stdout_json if isinstance(cli_result.stdout_json, dict) else {}
        return ExecutionResult(
            status="paper_filled",
            mode="paper",
            order_id=str(payload.get("order_id") or new_id("paper")),
            symbol=features.symbol,
            action=ensemble.action,
            requested_size_usd=size_usd,
            filled_size_usd=safe_float(payload.get("cost"), size_usd),
            fill_price=safe_float(payload.get("price"), features.last_price),
            volume=safe_float(payload.get("volume"), volume),
            fee=safe_float(payload.get("fee"), 0.0),
            raw=payload,
        )

    if mode == "live":
        if not s.all_live_flags_on():
            return _build_blocked(
                mode="live",
                features=features,
                ensemble=ensemble,
                reason="live trading not enabled (triple opt-in missing)",
            )
        size_usd = min(size_usd, exec_cfg.live_size_usd)
        volume = size_usd / max(features.last_price, 0.01)
        # Optional pre-flight validation against the live endpoint.
        if exec_cfg.require_validate_first:
            v = kraken_cli.validate_live_order(
                symbol_pair=sym.pair_slash,
                action=ensemble.action,
                volume=round(volume, 6),
            )
            if not v.ok:
                return ExecutionResult(
                    status="live_failed",
                    mode="live",
                    symbol=features.symbol,
                    action=ensemble.action,
                    requested_size_usd=size_usd,
                    error=f"live validate failed: {v.stderr[:200]}",
                    raw={"validate": v.__dict__},
                )
        cli_result = kraken_cli.place_order(
            mode="live",
            symbol_pair=sym.pair_slash,
            action=ensemble.action,
            volume=round(volume, 6),
        )
        if not cli_result.ok:
            return ExecutionResult(
                status="live_failed",
                mode="live",
                symbol=features.symbol,
                action=ensemble.action,
                requested_size_usd=size_usd,
                error=f"live order failed: {cli_result.stderr[:200]}",
                raw={"cli": cli_result.__dict__},
            )
        payload = cli_result.stdout_json if isinstance(cli_result.stdout_json, dict) else {}
        return ExecutionResult(
            status="live_filled",
            mode="live",
            order_id=str(payload.get("order_id") or new_id("live")),
            symbol=features.symbol,
            action=ensemble.action,
            requested_size_usd=size_usd,
            filled_size_usd=safe_float(payload.get("cost"), size_usd),
            fill_price=safe_float(payload.get("price"), features.last_price),
            volume=safe_float(payload.get("volume"), volume),
            fee=safe_float(payload.get("fee"), 0.0),
            raw=payload,
        )

    return _build_blocked(
        mode=mode,
        features=features,
        ensemble=ensemble,
        reason=f"unknown trading mode: {mode}",
    )


def apply_to_portfolio(decision: Decision) -> None:
    portfolio.record_fill(decision.execution)


__all__ = ["execute", "apply_to_portfolio", "reset_paper_init_cache"]
