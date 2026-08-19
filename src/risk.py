"""Risk manager — the only place that decides whether an order can leave."""

from __future__ import annotations

import time
from collections.abc import Iterable

from .config import Settings, get_settings
from .schemas import EnsembleResult, Features, PortfolioSnapshot, RiskCheck, RiskResult
from .universe import is_in_allowlist

# Intransigeant ceiling for the futures pivot. The risk gate refuses any
# value strictly above this no matter where it came from (config, env,
# caller override). The wrapper in :mod:`src.futures_kraken_cli` enforces
# the same ceiling as a belt-and-suspenders barrier.
HARDCODED_MAX_LEVERAGE: float = 1.0


_LAST_TRADE_TS: dict[str, float] = {}
_RECENT_TRADE_TIMES: list[float] = []


def reset_cooldowns() -> None:
    _LAST_TRADE_TS.clear()
    _RECENT_TRADE_TIMES.clear()


def mark_traded(symbol: str, *, when: float | None = None) -> None:
    ts = when if when is not None else time.time()
    _LAST_TRADE_TS[symbol] = ts
    _RECENT_TRADE_TIMES.append(ts)
    # Trim to last 2h so the structure cannot grow unbounded during long runs.
    cutoff = ts - 7200
    while _RECENT_TRADE_TIMES and _RECENT_TRADE_TIMES[0] < cutoff:
        _RECENT_TRADE_TIMES.pop(0)


def _trades_in_last_hour(now: float | None = None) -> int:
    now = now if now is not None else time.time()
    cutoff = now - 3600
    return sum(1 for t in _RECENT_TRADE_TIMES if t >= cutoff)


def _check(name: str, passed: bool, detail: str = "") -> RiskCheck:
    return RiskCheck(name=name, passed=passed, detail=detail)


def evaluate_risk(
    *,
    ensemble: EnsembleResult,
    features: Features,
    portfolio: PortfolioSnapshot,
    settings: Settings | None = None,
    intended_mode: str | None = None,
    is_exit_action: bool = False,
    intended_leverage: float | None = None,
) -> RiskResult:
    """Evaluate the risk gates for an upcoming order.

    ``is_exit_action=True`` softens the entry-time gates (min confidence,
    regime guard, cooldown) for a SELL that is the result of an
    exit-rule firing. The triple opt-in for live, allowlist, drawdown
    circuit-breaker and spread guard remain enforced regardless.

    ``intended_leverage`` is the leverage the caller wants to apply on the
    futures engine. When ``None`` it defaults to ``futures.max_leverage``
    (currently always 1.0). The gate **refuses** any value strictly above
    ``HARDCODED_MAX_LEVERAGE`` regardless of how the caller produced it.
    """
    settings = settings or get_settings()
    cfg = settings.config.risk
    strat = settings.config.strategy
    exec_cfg = settings.config.execution
    futures_cfg = settings.config.futures
    env = settings.env
    mode = (intended_mode or env.trading_mode or "dry_run").lower()
    engine = (exec_cfg.engine or "spot").lower()

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

    # 3) Minimum confidence (entry-time gate — softened for exit actions).
    min_conf = strat.min_confidence_to_trade
    conf_ok = ensemble.confidence >= min_conf
    if is_exit_action:
        checks.append(_check("min_confidence", True, "bypassed (exit_rule SELL)"))
    else:
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

    # 5) Regime guard (entry-time gate — bypassed for exit-rule SELL so an
    # exit can fire even on LOW_LIQUIDITY books).
    regime_blocked = ensemble.regime in cfg.block_if_regime
    if is_exit_action:
        checks.append(_check("regime", True, f"regime={ensemble.regime} bypassed (exit_rule SELL)"))
    else:
        checks.append(
            _check("regime", not regime_blocked, f"regime={ensemble.regime} blocked={cfg.block_if_regime}")
        )
        if regime_blocked:
            reasons.append(f"regime {ensemble.regime} blocked by config")

    # 6) Cooldown (entry-time gate — bypassed for exits).
    last = _LAST_TRADE_TS.get(features.symbol)
    cooldown_ok = True
    if last is not None:
        elapsed = time.time() - last
        cooldown_ok = elapsed >= cfg.cooldown_seconds_per_symbol
        if is_exit_action:
            checks.append(_check("cooldown", True, f"elapsed={elapsed:.0f}s bypassed (exit_rule SELL)"))
        else:
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
    # Exit-only SELLs are reduce-only by construction (they never increase
    # exposure — they close an existing long). Without this carve-out the
    # symmetric ``current_exposure + adjusted <= cap`` check would block
    # exits whenever the agent is already at the per-account exposure
    # ceiling, which is exactly when an exit is most needed. The carve-out
    # also bypasses the per-position notional cap for the SELL leg so the
    # full open quantity can be flattened in one shot (otherwise a 44 USD
    # position would only get a 25 USD partial exit).
    current_exposure = sum(abs(p.notional_usd) for p in portfolio.positions)
    size_cap = {
        "dry_run": exec_cfg.dry_run_size_usd,
        "paper": exec_cfg.paper_size_usd,
        "live": exec_cfg.live_size_usd,
    }.get(mode, exec_cfg.dry_run_size_usd)
    if is_exit_action and ensemble.action == "SELL":
        suggested = float(ensemble.suggested_size_usd or 0.0)
        adjusted = max(suggested, 0.0)
        exposure_ok = True
        checks.append(
            _check(
                "max_total_exposure",
                True,
                f"current={current_exposure:.2f} sell_exit bypasses cap (adjusted={adjusted:.2f})",
            )
        )
    else:
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

    # 10) Trade rate limiter (per profile).
    max_trades_hour = getattr(cfg, "max_trades_per_hour", 0) or 0
    rate_ok = True
    if max_trades_hour > 0:
        recent = _trades_in_last_hour()
        rate_ok = recent < max_trades_hour
        checks.append(
            _check(
                "max_trades_per_hour",
                rate_ok,
                f"recent={recent} max={max_trades_hour}",
            )
        )
        if not rate_ok:
            reasons.append(
                f"trade rate {recent}/h exceeds profile cap of {max_trades_hour}/h"
            )

    # 11) Leverage cap — intransigeant. The futures pivot keeps the bot at
    # 1x effective leverage (= spot equivalent). Any caller asking for
    # leverage > 1.0 is refused, regardless of the config/env source.
    cfg_max_lev = float(getattr(futures_cfg, "max_leverage", HARDCODED_MAX_LEVERAGE))
    effective_max_lev = min(cfg_max_lev, HARDCODED_MAX_LEVERAGE)
    requested_lev = (
        float(intended_leverage)
        if intended_leverage is not None
        else effective_max_lev
    )
    leverage_ok = requested_lev <= HARDCODED_MAX_LEVERAGE + 1e-9 and cfg_max_lev <= HARDCODED_MAX_LEVERAGE + 1e-9
    checks.append(
        _check(
            "max_leverage",
            leverage_ok,
            (
                f"requested={requested_lev:.3f}x config_max={cfg_max_lev:.3f}x "
                f"hard_cap={HARDCODED_MAX_LEVERAGE:.3f}x"
            ),
        )
    )
    if not leverage_ok:
        reasons.append(
            f"leverage {requested_lev:.3f}x exceeds hardcoded cap "
            f"{HARDCODED_MAX_LEVERAGE:.1f}x (config_max={cfg_max_lev:.3f}x)"
        )

    # 12) Funding-rate gate — only enforced on futures BUYs. The cap is the
    # ``futures.max_funding_rate_pct_per_hour`` config knob (default 0.5%/h).
    # SELL exits and HOLDs are exempt: we want to be able to flatten a
    # position even when the funding rate spiked.
    funding_threshold = float(
        getattr(futures_cfg, "max_funding_rate_pct_per_hour", 0.5)
    )
    funding_rate = getattr(features, "funding_rate_pct_per_hour", None)
    funding_blocks_buy = (
        engine == "futures"
        and ensemble.action == "BUY"
        and funding_rate is not None
        and float(funding_rate) > funding_threshold
    )
    if engine == "futures" and ensemble.action == "BUY" and funding_rate is not None:
        funding_ok = not funding_blocks_buy
        checks.append(
            _check(
                "max_funding_rate",
                funding_ok,
                (
                    f"funding={float(funding_rate):+.3f}%/h "
                    f"cap={funding_threshold:.3f}%/h"
                ),
            )
        )
        if funding_blocks_buy:
            reasons.append(
                f"funding rate {float(funding_rate):+.3f}%/h above "
                f"{funding_threshold:.3f}%/h cap on futures engine"
            )
    else:
        checks.append(
            _check(
                "max_funding_rate",
                True,
                (
                    f"engine={engine} action={ensemble.action} "
                    f"funding={funding_rate} (gate inactive)"
                ),
            )
        )

    # 13) Live-trading triple opt-in.
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
