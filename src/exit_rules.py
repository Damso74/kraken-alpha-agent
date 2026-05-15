"""Deterministic exit-rules engine.

This module is pure: it inspects an open ``Position`` together with a fresh
mark, the latest opportunity score, and the current UTC time, and returns
an :class:`ExitDecision` describing whether (and why) the position should
be flattened. The agent loop then converts the intent to a clamped SELL
*after* the strategy/actionability/risk pipeline.

Hard guarantees (also covered by ``tests/test_exit_rules.py``):

* No exit rule ever opens a short. Every rule pre-checks that
  ``position.quantity > 0``.
* SELL size is clamped to the open quantity by the caller. The exit
  engine only signals the *intent* to flatten.
* The triple opt-in for live trading is untouched: the engine produces a
  SELL intent, then the existing risk gate decides whether it can leave.
* ``LOW_LIQUIDITY`` blocking on BUY is unaffected — this module never
  loosens any safety rule.

Configuration lookup order (the first one defined wins):

1. Profile-level overrides on the ``risk`` config block
   (``risk.stop_loss_pct``, ``risk.take_profit_pct``).
2. The dedicated ``exit:`` block (:class:`src.config.ExitRulesConfig`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .sessions import minutes_until_us_core_close


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExitDecision:
    """Outcome of an exit-rules evaluation pass."""

    should_exit: bool
    reason: Optional[str] = None
    pnl_pct: Optional[float] = None
    held_minutes: Optional[float] = None
    rule: Optional[str] = None


# Internal helper view of the merged exit configuration.
@dataclass(frozen=True)
class _ExitParams:
    stop_loss_pct: float
    take_profit_pct: float
    momentum_exit_score: float
    max_hold_minutes: float
    stale_position_min_pnl_pct: float
    flatten_before_close_minutes: float
    flatten_before_close_enabled: bool = True
    momentum_exit_enabled: bool = True


# ---------------------------------------------------------------------------
# Config & timestamp helpers
# ---------------------------------------------------------------------------


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _resolve_params(config: Any) -> _ExitParams:
    """Merge profile-level ``risk`` overrides with ``exit:`` defaults.

    ``config`` may be a :class:`src.config.YAMLConfig`, a :class:`Settings`
    instance, or any mapping/object exposing ``risk`` and ``exit`` fields.
    """
    if config is None:
        from .config import get_settings

        config = get_settings().config
    # If a Settings instance was passed, drill into .config.
    cfg = getattr(config, "config", config)

    risk = _get_attr(cfg, "risk")
    exit_cfg = _get_attr(cfg, "exit")

    risk_stop = _get_attr(risk, "stop_loss_pct")
    risk_take = _get_attr(risk, "take_profit_pct")
    base_stop = _get_attr(exit_cfg, "stop_loss_pct", 1.5)
    base_take = _get_attr(exit_cfg, "take_profit_pct", 2.0)

    stop = float(risk_stop) if risk_stop is not None else float(base_stop)
    take = float(risk_take) if risk_take is not None else float(base_take)

    # ``time_stop_minutes`` is the crypto-fast-rotation alias; when set,
    # it overrides the legacy ``max_hold_minutes``. Both keep being read
    # so the existing xStocks profiles are unaffected.
    base_max_hold = float(_get_attr(exit_cfg, "max_hold_minutes", 90.0))
    time_stop_alias = _get_attr(exit_cfg, "time_stop_minutes", None)
    max_hold = float(time_stop_alias) if time_stop_alias is not None else base_max_hold

    return _ExitParams(
        stop_loss_pct=stop,
        take_profit_pct=take,
        momentum_exit_score=float(
            _get_attr(exit_cfg, "momentum_exit_score", -0.03)
        ),
        max_hold_minutes=max_hold,
        stale_position_min_pnl_pct=float(
            _get_attr(exit_cfg, "stale_position_min_pnl_pct", 0.3)
        ),
        flatten_before_close_minutes=float(
            _get_attr(exit_cfg, "flatten_before_close_minutes", 15.0)
        ),
        flatten_before_close_enabled=bool(
            _get_attr(exit_cfg, "flatten_before_close_enabled", True)
        ),
        momentum_exit_enabled=bool(
            _get_attr(exit_cfg, "momentum_exit_enabled", True)
        ),
    )


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(s)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_utc(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _pnl_pct(position: Any, current_price: float) -> Optional[float]:
    avg = float(_get_attr(position, "avg_entry_price", 0.0) or 0.0)
    if avg <= 0:
        return None
    return (float(current_price) - avg) / avg * 100.0


def _held_minutes(position: Any, now: datetime) -> Optional[float]:
    opened_at = _get_attr(position, "opened_at")
    parsed = _parse_iso(opened_at) if isinstance(opened_at, str) else None
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds() / 60.0)


def _is_long(position: Any) -> bool:
    qty = float(_get_attr(position, "quantity", 0.0) or 0.0)
    return qty > 1e-9


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def stop_loss_exit(position: Any, current_price: float, config: Any = None) -> ExitDecision:
    """SELL when ``pnl_pct <= -stop_loss_pct``. Never opens a short."""
    if not _is_long(position):
        return ExitDecision(should_exit=False, rule=None)
    params = _resolve_params(config)
    pnl = _pnl_pct(position, current_price)
    if pnl is None:
        return ExitDecision(should_exit=False, pnl_pct=None)
    if pnl <= -abs(params.stop_loss_pct):
        return ExitDecision(
            should_exit=True,
            reason=f"stop_loss(pnl={pnl:+.2f}%<=-{params.stop_loss_pct:.2f}%)",
            pnl_pct=pnl,
            rule="stop_loss",
        )
    return ExitDecision(should_exit=False, pnl_pct=pnl)


def take_profit_exit(position: Any, current_price: float, config: Any = None) -> ExitDecision:
    """SELL when ``pnl_pct >= take_profit_pct``."""
    if not _is_long(position):
        return ExitDecision(should_exit=False, rule=None)
    params = _resolve_params(config)
    pnl = _pnl_pct(position, current_price)
    if pnl is None:
        return ExitDecision(should_exit=False, pnl_pct=None)
    if pnl >= abs(params.take_profit_pct):
        return ExitDecision(
            should_exit=True,
            reason=f"take_profit(pnl={pnl:+.2f}%>={params.take_profit_pct:.2f}%)",
            pnl_pct=pnl,
            rule="take_profit",
        )
    return ExitDecision(should_exit=False, pnl_pct=pnl)


def momentum_exit(position: Any, opportunity_score: float, config: Any = None) -> ExitDecision:
    """SELL when the latest opportunity score drops to/under the floor."""
    if not _is_long(position):
        return ExitDecision(should_exit=False, rule=None)
    params = _resolve_params(config)
    if not params.momentum_exit_enabled:
        return ExitDecision(should_exit=False)
    try:
        score = float(opportunity_score)
    except (TypeError, ValueError):
        return ExitDecision(should_exit=False)
    if score <= params.momentum_exit_score:
        return ExitDecision(
            should_exit=True,
            reason=f"momentum_exit(score={score:+.3f}<={params.momentum_exit_score:+.3f})",
            rule="momentum_exit",
        )
    return ExitDecision(should_exit=False)


def time_exit(position: Any, now: Optional[datetime], config: Any = None) -> ExitDecision:
    """SELL when the position is older than ``max_hold_minutes`` AND PnL is stale.

    The "stale" guard prevents flushing a still-winning position that just
    needs more time to reach the take-profit.
    """
    if not _is_long(position):
        return ExitDecision(should_exit=False, rule=None)
    params = _resolve_params(config)
    now_utc = _ensure_utc(now)
    held = _held_minutes(position, now_utc)
    if held is None:
        # No ``opened_at`` known → cannot fire the rule safely.
        return ExitDecision(should_exit=False, held_minutes=None)
    pnl = _pnl_pct(position, float(_get_attr(position, "market_price", 0.0) or 0.0))
    if held >= params.max_hold_minutes and (pnl is None or pnl < params.stale_position_min_pnl_pct):
        return ExitDecision(
            should_exit=True,
            reason=(
                f"time_exit(held={held:.1f}min>={params.max_hold_minutes:.0f}min, "
                f"pnl={pnl if pnl is not None else 0.0:+.2f}%<{params.stale_position_min_pnl_pct:.2f}%)"
            ),
            pnl_pct=pnl,
            held_minutes=held,
            rule="time_exit",
        )
    return ExitDecision(should_exit=False, pnl_pct=pnl, held_minutes=held)


def flatten_before_close_exit(
    position: Any, now: Optional[datetime], config: Any = None
) -> ExitDecision:
    """SELL when the US_CORE close is closer than ``flatten_before_close_minutes``."""
    if not _is_long(position):
        return ExitDecision(should_exit=False, rule=None)
    params = _resolve_params(config)
    if not params.flatten_before_close_enabled:
        return ExitDecision(should_exit=False)
    now_utc = _ensure_utc(now)
    remaining = minutes_until_us_core_close(now_utc)
    if remaining is None:
        # Outside the weekday core window — rule cannot fire.
        return ExitDecision(should_exit=False)
    if remaining <= params.flatten_before_close_minutes:
        return ExitDecision(
            should_exit=True,
            reason=(
                f"flatten_before_close(remaining={remaining:.1f}min"
                f"<={params.flatten_before_close_minutes:.0f}min)"
            ),
            rule="flatten_before_close",
        )
    return ExitDecision(should_exit=False)


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def evaluate_exit_rules(
    position: Any,
    current_price: float,
    opportunity_score: float,
    now: Optional[datetime],
    config: Any = None,
) -> ExitDecision:
    """Walk the configured rules in priority order and return the first hit.

    Priority (matches the user's brief):
    stop_loss → take_profit → momentum_exit → time_exit → flatten_before_close

    Returns a no-op :class:`ExitDecision` when none of the rules fire — the
    caller can then keep the original BUY/HOLD/SELL intent.
    """
    if not _is_long(position):
        return ExitDecision(should_exit=False, rule=None)

    now_utc = _ensure_utc(now)
    pnl = _pnl_pct(position, current_price)
    held = _held_minutes(position, now_utc)

    for rule_fn, args in (
        (stop_loss_exit, (position, current_price, config)),
        (take_profit_exit, (position, current_price, config)),
        (momentum_exit, (position, opportunity_score, config)),
        (time_exit, (position, now_utc, config)),
        (flatten_before_close_exit, (position, now_utc, config)),
    ):
        outcome = rule_fn(*args)
        if outcome.should_exit:
            return ExitDecision(
                should_exit=True,
                reason=outcome.reason,
                pnl_pct=outcome.pnl_pct if outcome.pnl_pct is not None else pnl,
                held_minutes=outcome.held_minutes if outcome.held_minutes is not None else held,
                rule=outcome.rule,
            )

    return ExitDecision(
        should_exit=False,
        pnl_pct=pnl,
        held_minutes=held,
        rule=None,
    )


__all__ = [
    "ExitDecision",
    "stop_loss_exit",
    "take_profit_exit",
    "momentum_exit",
    "time_exit",
    "flatten_before_close_exit",
    "evaluate_exit_rules",
]
