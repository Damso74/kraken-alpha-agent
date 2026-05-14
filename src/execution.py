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

from typing import Any

from . import kraken_cli, portfolio
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


def execute(
    *,
    features: Features,
    ensemble: EnsembleResult,
    risk: RiskResult,
) -> ExecutionResult:
    s = get_settings()
    mode = (s.env.trading_mode or "dry_run").lower()
    exec_cfg = s.config.execution

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


__all__ = ["execute", "apply_to_portfolio"]
