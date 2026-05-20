"""Kill switch and micro-live guardrails (Phase 20, dry-run only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GuardrailConfig:
    max_capital_usd: float = 20.0
    max_daily_loss_usd: float = 5.0
    max_total_loss_usd: float = 10.0
    max_orders_per_day: int = 10
    max_position_usd: float = 10.0
    manual_approval_required: bool = True
    allowed_assets: frozenset[str] = field(default_factory=lambda: frozenset({"BTC", "ETH"}))
    dry_run_passed: bool = False
    stale_data: bool = False


@dataclass
class GuardrailState:
    starting_capital_usd: float = 20.0
    current_equity_usd: float = 20.0
    daily_pnl_usd: float = 0.0
    orders_today: int = 0
    manual_approval_granted: bool = False


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason: str


DEFAULT_STOP_FILE = Path("reports/paper_daemon_state/STOP_TRADING")


def emergency_stop_active(stop_file: Path | str | None = None) -> bool:
    path = Path(stop_file) if stop_file else DEFAULT_STOP_FILE
    return path.is_file()


def evaluate_guardrails(
    *,
    config: GuardrailConfig,
    state: GuardrailState,
    symbol: str,
    notional_usd: float,
    stop_file: Path | str | None = None,
) -> GuardrailDecision:
    if emergency_stop_active(stop_file):
        return GuardrailDecision(False, "emergency_stop_file")

    sym = symbol.upper().partition("/")[0]
    if sym not in config.allowed_assets:
        return GuardrailDecision(False, "asset_not_allowed")

    if config.stale_data:
        return GuardrailDecision(False, "stale_data")

    if not config.dry_run_passed:
        return GuardrailDecision(False, "dry_run_not_passed")

    if config.manual_approval_required and not state.manual_approval_granted:
        return GuardrailDecision(False, "manual_approval_required")

    if notional_usd > config.max_position_usd + 1e-9:
        return GuardrailDecision(False, "max_position_exceeded")

    if state.orders_today >= config.max_orders_per_day:
        return GuardrailDecision(False, "max_orders_per_day")

    if state.daily_pnl_usd <= -config.max_daily_loss_usd:
        return GuardrailDecision(False, "max_daily_loss")

    total_loss = state.starting_capital_usd - state.current_equity_usd
    if total_loss >= config.max_total_loss_usd:
        return GuardrailDecision(False, "max_total_loss")

    if state.current_equity_usd > config.max_capital_usd + 1e-9:
        return GuardrailDecision(False, "max_capital_exceeded")

    return GuardrailDecision(True, "ok")


def guardrail_report(config: GuardrailConfig, state: GuardrailState) -> dict[str, Any]:
    return {
        "max_capital_usd": config.max_capital_usd,
        "current_equity_usd": state.current_equity_usd,
        "daily_pnl_usd": state.daily_pnl_usd,
        "orders_today": state.orders_today,
        "manual_approval_required": config.manual_approval_required,
        "manual_approval_granted": state.manual_approval_granted,
        "dry_run_passed": config.dry_run_passed,
    }
