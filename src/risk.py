"""Risk manager — the only place that decides whether an order can leave."""

from __future__ import annotations

import time
from typing import Iterable

from .config import Settings, get_settings
from .schemas import EnsembleResult, Features, PortfolioSnapshot, RiskCheck, RiskResult
from .universe import is_in_allowlist


_LAST_TRADE_TS: dict[str, float] = {}


def reset_cooldowns() -> None:
    _LAST_TRADE_TS.clear()


def mark_traded(symbol: str, *, when: float | None = None) -> None:
    _LAST_TRADE_TS[symbol] = when if when is not None else time.time()


def _check(name: str, passed: bool, detail: str = "") -> RiskCheck:
    return RiskCheck(name=name, passed=passed, detail=detail)


def evaluate_risk(
    *,
    ensemble: EnsembleResult,
    features: Features,
    portfolio: PortfolioSnapshot,
    settings: Settings | None = None,
    intended_mode: str | None = None,
) -> RiskResult:
    settings = settings or get_settings()
    cfg = settings.config.risk
    strat = settings.config.strategy
    exec_cfg = settings.config.execution
    env = settings.env
    mode = (intended_mode or env.trading_mode or "dry_run").lower()

    checks: list[RiskCheck] = []
    reasons: list[str] = []

    # 1) Allowlist gate.
    in_allow = is_in_allowlist(features.symbol)
    checks.append(_check("allowlist", in_allow, f"symbol={features.symbol}"))
    if cfg.block_unknown_symbol and not in_allow:
        reasons.append(f"symbol {features.symbol} not in allowlist")

    # 2) Action vs threshold (HOLD is always safe to log but won't be approved).
    is_actionable = ensemble.action in ("BUY", "SELL")
    checks.append(_check("actionable", is_actionable, f"action={ensemble.action}"))
    if not is_actionable:
        reasons.append("ensemble action is HOLD")

    # 3) Minimum confidence.
    min_conf = strat.min_confidence_to_trade
    conf_ok = ensemble.confidence >= min_conf
    checks.append(_check("min_confidence", conf_ok, f"conf={ensemble.confidence:.2f} min={min_conf}"))
    if not conf_ok:
        reasons.append(f"confidence {ensemble.confidence:.2f} below threshold {min_conf}")

    # 4) Spread guard.
    spread_ok = features.spread_bps <= cfg.max_spread_bps
    checks.append(
        _check("max_spread_bps", spread_ok, f"spread={features.spread_bps:.1f} max={cfg.max_spread_bps}")
    )
    if not spread_ok:
        reasons.append(f"spread {features.spread_bps:.1f}bps above {cfg.max_spread_bps}bps")

    # 5) Regime guard.
    regime_blocked = ensemble.regime in cfg.block_if_regime
    checks.append(
        _check("regime", not regime_blocked, f"regime={ensemble.regime} blocked={cfg.block_if_regime}")
    )
    if regime_blocked:
        reasons.append(f"regime {ensemble.regime} blocked by config")

    # 6) Cooldown.
    last = _LAST_TRADE_TS.get(features.symbol)
    cooldown_ok = True
    if last is not None:
        elapsed = time.time() - last
        cooldown_ok = elapsed >= cfg.cooldown_seconds_per_symbol
        checks.append(
            _check(
                "cooldown",
                cooldown_ok,
                f"elapsed={elapsed:.0f}s required={cfg.cooldown_seconds_per_symbol}s",
            )
        )
        if not cooldown_ok:
            reasons.append(
                f"cooldown active for {features.symbol} ({elapsed:.0f}s/{cfg.cooldown_seconds_per_symbol}s)"
            )
    else:
        checks.append(_check("cooldown", True, "no previous trade"))

    # 7) Max open positions.
    open_count = sum(1 for p in portfolio.positions if abs(p.quantity) > 1e-9)
    pos_ok = open_count < cfg.max_open_positions or ensemble.action == "SELL"
    checks.append(_check("max_open_positions", pos_ok, f"open={open_count} max={cfg.max_open_positions}"))
    if not pos_ok:
        reasons.append(f"already holding {open_count} positions (max {cfg.max_open_positions})")

    # 8) Exposure caps.
    current_exposure = sum(abs(p.notional_usd) for p in portfolio.positions)
    size_cap = {
        "dry_run": exec_cfg.dry_run_size_usd,
        "paper": exec_cfg.paper_size_usd,
        "live": exec_cfg.live_size_usd,
    }.get(mode, exec_cfg.dry_run_size_usd)
    suggested = min(ensemble.suggested_size_usd, cfg.max_position_notional_usd, size_cap)
    adjusted = max(suggested, 0.0)
    exposure_ok = (current_exposure + adjusted) <= cfg.max_total_exposure_usd
    checks.append(
        _check(
            "max_total_exposure",
            exposure_ok,
            f"current={current_exposure:.2f} adding={adjusted:.2f} cap={cfg.max_total_exposure_usd}",
        )
    )
    if not exposure_ok:
        reasons.append(
            f"exposure {current_exposure + adjusted:.2f} would exceed cap {cfg.max_total_exposure_usd}"
        )

    # 9) Drawdown circuit-breaker.
    starting = settings.config.competition.starting_equity_usd or 0.0
    drawdown_pct = 0.0
    if starting > 0 and portfolio.equity_usd > 0:
        drawdown_pct = max(0.0, (starting - portfolio.equity_usd) / starting * 100.0)
    dd_ok = drawdown_pct <= cfg.max_daily_drawdown_pct
    checks.append(
        _check(
            "max_daily_drawdown",
            dd_ok,
            f"drawdown={drawdown_pct:.2f}% max={cfg.max_daily_drawdown_pct}%",
        )
    )
    if not dd_ok:
        reasons.append(
            f"drawdown {drawdown_pct:.2f}% above {cfg.max_daily_drawdown_pct}% cap"
        )

    # 10) Live-trading triple opt-in.
    blocked_for_live_flags = False
    if mode == "live":
        live_flags_ok = settings.all_live_flags_on()
        checks.append(
            _check(
                "live_flags",
                live_flags_ok,
                "TRADING_MODE=live & LIVE_TRADING=true & ALLOW_LIVE_ORDERS=true",
            )
        )
        if not live_flags_ok:
            blocked_for_live_flags = True
            reasons.append("live trading blocked: triple opt-in not satisfied")
    else:
        checks.append(_check("live_flags", True, f"mode={mode} (not live)"))

    approved = len(reasons) == 0 and not blocked_for_live_flags
    return RiskResult(
        approved=approved,
        reasons=reasons,
        checks=checks,
        adjusted_size_usd=adjusted if approved else 0.0,
        blocked_for_live_flags=blocked_for_live_flags,
    )


def summarise(checks: Iterable[RiskCheck]) -> str:
    items = [f"{c.name}={'OK' if c.passed else 'FAIL'}" for c in checks]
    return " | ".join(items)


__all__ = ["evaluate_risk", "mark_traded", "reset_cooldowns", "summarise"]
