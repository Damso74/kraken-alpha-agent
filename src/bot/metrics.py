"""Backtest metrics and tournament verdict logic."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

Verdict = Literal[
    "kill",
    "blocked_costs",
    "blocked_risk",
    "paper_candidate",
    "blocked_data",
    "insufficient_trades",
    "insufficient_candles",
    "weak",
    "micro_live_candidate",
]

VERDICT_ORDER = (
    "blocked_data",
    "insufficient_candles",
    "insufficient_trades",
    "blocked_risk",
    "blocked_costs",
    "kill",
    "weak",
    "paper_candidate",
    "micro_live_candidate",
)

MIN_TRADES_FOR_VERDICT = 5
MIN_TRADES_BY_TIMEFRAME: dict[str, int] = {"1d": 5, "4h": 10, "1h": 20}
MIN_CANDLES_BY_TIMEFRAME: dict[str, int] = {"1d": 60, "4h": 120, "1h": 240}

MAX_COST_DRAG_PCT = 0.40
MIN_RETURN_FOR_CANDIDATE = -0.05
MAX_DRAWDOWN_FOR_CANDIDATE = 0.20
MIN_SHARPE_FOR_CANDIDATE = 0.0
MIN_RETURN_FOR_WEAK = -0.15
MAX_DRAWDOWN_FOR_WEAK = 0.25
MAX_RISK_DENIAL_RATE = 0.30
MAX_DRAWDOWN_RISK_BLOCK_PCT = 15.0
SAFETY_STOP_RULES = frozenset({"max_drawdown_pct", "max_daily_loss_pct"})


@dataclass
class BacktestMetrics:
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    trade_count: int = 0
    fees_usd: float = 0.0
    slippage_drag_usd: float = 0.0
    cost_drag_pct: float = 0.0
    final_equity: float = 0.0
    starting_equity: float = 0.0
    candle_count: int = 0
    usable_bars: int = 0


@dataclass
class VerdictResult:
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)
    micro_live_enabled: bool = False


@dataclass
class RiskRunStats:
    risk_denials_count: int = 0
    risk_checks_count: int = 0
    risk_rules_triggered: list[str] = field(default_factory=list)
    stopped_by_risk: bool = False
    grid_inventory_exceeded: bool = False
    invalid_exposure: bool = False

    @property
    def risk_denial_rate(self) -> float:
        if self.risk_checks_count <= 0:
            return 0.0
        return self.risk_denials_count / self.risk_checks_count


def _max_drawdown(equity_curve: Sequence[float]) -> float:
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        if peak > 1e-12:
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)
    return max_dd


def _sharpe(daily_returns: Sequence[float], *, annualization: float = 252.0) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    var = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    if var <= 1e-18:
        return 0.0
    return mean / math.sqrt(var) * math.sqrt(annualization)


def _annualization_factor(timeframe: str) -> float:
    tf = timeframe.strip().lower()
    if tf == "1h":
        return 24.0 * 365.0
    if tf == "4h":
        return 6.0 * 365.0
    return 252.0


def compute_metrics(
    *,
    equity_curve: Sequence[float],
    trade_pnls: Sequence[float],
    fees_usd: float,
    slippage_drag_usd: float,
    starting_equity: float,
    candle_count: int = 0,
    usable_bars: int = 0,
    timeframe: str = "1d",
) -> BacktestMetrics:
    final_eq = equity_curve[-1] if equity_curve else starting_equity
    total_return = 0.0
    if starting_equity > 1e-12:
        total_return = (final_eq - starting_equity) / starting_equity * 100.0

    bar_returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        if prev > 1e-12:
            bar_returns.append((equity_curve[i] - prev) / prev)

    wins = sum(1 for p in trade_pnls if p > 0)
    trade_count = len(trade_pnls)
    win_rate = (wins / trade_count * 100.0) if trade_count else 0.0

    gross_pnl = sum(trade_pnls)
    cost_drag = 0.0
    if abs(gross_pnl) > 1e-9:
        cost_drag = (fees_usd + slippage_drag_usd) / abs(gross_pnl)
    elif fees_usd + slippage_drag_usd > 0:
        cost_drag = 1.0

    return BacktestMetrics(
        total_return_pct=total_return,
        sharpe_ratio=_sharpe(bar_returns, annualization=_annualization_factor(timeframe)),
        max_drawdown_pct=_max_drawdown(equity_curve) * 100.0,
        win_rate_pct=win_rate,
        trade_count=trade_count,
        fees_usd=fees_usd,
        slippage_drag_usd=slippage_drag_usd,
        cost_drag_pct=cost_drag * 100.0,
        final_equity=final_eq,
        starting_equity=starting_equity,
        candle_count=candle_count,
        usable_bars=usable_bars,
    )


def _blocked_risk_reasons(
    metrics: BacktestMetrics,
    risk_stats: RiskRunStats,
) -> list[str]:
    """blocked_risk only on sustained risk failure — not a single punctual deny."""
    reasons: list[str] = []
    if metrics.max_drawdown_pct > MAX_DRAWDOWN_RISK_BLOCK_PCT + 1e-9:
        reasons.append(f"max_drawdown_pct={metrics.max_drawdown_pct:.2f}")
    if risk_stats.risk_denial_rate > MAX_RISK_DENIAL_RATE + 1e-9:
        reasons.append(f"risk_denial_rate={risk_stats.risk_denial_rate:.2%}")
    if risk_stats.stopped_by_risk:
        reasons.append("safety_stop")
    if metrics.final_equity < 0:
        reasons.append("negative_portfolio")
    if risk_stats.invalid_exposure:
        reasons.append("invalid_exposure")
    if risk_stats.grid_inventory_exceeded:
        reasons.append("grid_max_inventory")
    if (
        metrics.trade_count == 0
        and risk_stats.risk_denials_count > 0
        and risk_stats.risk_checks_count > 0
    ):
        reasons.append("no_executable_trades")
    return reasons


def _min_trades_for(timeframe: str) -> int:
    return MIN_TRADES_BY_TIMEFRAME.get(timeframe.strip().lower(), MIN_TRADES_FOR_VERDICT)


def _min_candles_for(timeframe: str) -> int:
    return MIN_CANDLES_BY_TIMEFRAME.get(timeframe.strip().lower(), 60)


def classify_strategy_verdict(
    metrics: BacktestMetrics,
    context: Mapping[str, Any] | None = None,
) -> VerdictResult:
    """Centralized Phase 15 verdict classifier; never emits micro_live_candidate."""
    ctx = dict(context or {})
    timeframe = str(ctx.get("timeframe", "1d")).lower()
    data_ok = bool(ctx.get("data_ok", True))
    risk_stats = ctx.get("risk_stats")
    stats = risk_stats if isinstance(risk_stats, RiskRunStats) else RiskRunStats()

    if not data_ok:
        reason = str(ctx.get("blocked_reason", "missing or invalid OHLCV cache"))
        return VerdictResult("blocked_data", [reason])

    min_candles = _min_candles_for(timeframe)
    candle_count = int(ctx.get("candle_count", metrics.candle_count))
    usable_bars = int(ctx.get("usable_bars", metrics.usable_bars))
    enforce_candles = bool(
        ctx.get(
            "enforce_candle_minimum",
            candle_count > 0 or usable_bars > 0,
        )
    )
    if enforce_candles:
        if candle_count < min_candles:
            return VerdictResult(
                "insufficient_candles",
                [f"candle_count={candle_count} < {min_candles}"],
            )
        if usable_bars < min_candles:
            return VerdictResult(
                "insufficient_candles",
                [f"usable_bars={usable_bars} < {min_candles}"],
            )

    min_trades = _min_trades_for(timeframe)
    if metrics.trade_count < min_trades:
        return VerdictResult(
            "insufficient_trades",
            [f"trade_count={metrics.trade_count} < {min_trades}"],
        )

    risk_reasons = _blocked_risk_reasons(metrics, stats)
    if risk_reasons:
        return VerdictResult("blocked_risk", risk_reasons)

    if metrics.cost_drag_pct > MAX_COST_DRAG_PCT * 100.0:
        return VerdictResult(
            "blocked_costs",
            [f"cost_drag_pct={metrics.cost_drag_pct:.2f}"],
        )

    if (
        metrics.total_return_pct < MIN_RETURN_FOR_CANDIDATE * 100.0
        or metrics.max_drawdown_pct > MAX_DRAWDOWN_FOR_CANDIDATE * 100.0
    ):
        if (
            metrics.total_return_pct >= MIN_RETURN_FOR_WEAK * 100.0
            and metrics.max_drawdown_pct <= MAX_DRAWDOWN_FOR_WEAK * 100.0
        ):
            return VerdictResult(
                "weak",
                [
                    f"return={metrics.total_return_pct:.2f}% dd={metrics.max_drawdown_pct:.2f}% below paper bar"
                ],
            )
        return VerdictResult(
            "kill",
            [
                f"return={metrics.total_return_pct:.2f}% dd={metrics.max_drawdown_pct:.2f}%"
            ],
        )

    if metrics.sharpe_ratio < MIN_SHARPE_FOR_CANDIDATE:
        return VerdictResult("weak", [f"sharpe={metrics.sharpe_ratio:.3f}"])

    return VerdictResult("paper_candidate", ["meets paper thresholds"])


def compute_verdict(
    metrics: BacktestMetrics,
    *,
    data_ok: bool = True,
    risk_stats: RiskRunStats | None = None,
    allow_micro_live: bool = False,
    timeframe: str = "1d",
    candle_count: int = 0,
    usable_bars: int = 0,
) -> VerdictResult:
    """Assign tournament verdict; micro_live_candidate disabled unless explicitly allowed."""
    result = classify_strategy_verdict(
        metrics,
        {
            "timeframe": timeframe,
            "data_ok": data_ok,
            "risk_stats": risk_stats or RiskRunStats(),
            "candle_count": candle_count or metrics.candle_count,
            "usable_bars": usable_bars or metrics.usable_bars,
        },
    )
    if allow_micro_live and result.verdict == "paper_candidate":
        if metrics.sharpe_ratio > 1.0 and metrics.total_return_pct > 5.0:
            return VerdictResult(
                "micro_live_candidate",
                ["explicit opt-in only"],
                micro_live_enabled=True,
            )
    return result


def metrics_to_dict(metrics: BacktestMetrics, risk_stats: RiskRunStats | None = None) -> dict[str, Any]:
    """Serialize metrics + risk fields for tournament JSON/CSV."""
    stats = risk_stats or RiskRunStats()
    return {
        "total_return_pct": metrics.total_return_pct,
        "sharpe_ratio": metrics.sharpe_ratio,
        "max_drawdown_pct": metrics.max_drawdown_pct,
        "win_rate_pct": metrics.win_rate_pct,
        "trade_count": metrics.trade_count,
        "fees_usd": metrics.fees_usd,
        "slippage_drag_usd": metrics.slippage_drag_usd,
        "cost_drag_pct": metrics.cost_drag_pct,
        "final_equity": metrics.final_equity,
        "starting_equity": metrics.starting_equity,
        "candle_count": metrics.candle_count,
        "usable_bars": metrics.usable_bars,
        "risk_denials_count": stats.risk_denials_count,
        "risk_denial_rate": round(stats.risk_denial_rate, 4),
        "risk_rules_triggered": stats.risk_rules_triggered,
        "stopped_by_risk": stats.stopped_by_risk,
    }
