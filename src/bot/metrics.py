"""Backtest metrics and tournament verdict logic."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Sequence

Verdict = Literal[
    "kill",
    "blocked_costs",
    "blocked_risk",
    "paper_candidate",
    "blocked_data",
    "insufficient_trades",
    "micro_live_candidate",
]

VERDICT_ORDER = (
    "blocked_data",
    "insufficient_trades",
    "blocked_risk",
    "blocked_costs",
    "kill",
    "paper_candidate",
    "micro_live_candidate",
)

MIN_TRADES_FOR_VERDICT = 5
MAX_COST_DRAG_PCT = 0.40
MIN_RETURN_FOR_CANDIDATE = -0.05
MAX_DRAWDOWN_FOR_CANDIDATE = 0.20
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


def _sharpe(daily_returns: Sequence[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    var = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    if var <= 1e-18:
        return 0.0
    return mean / math.sqrt(var) * math.sqrt(252)


def compute_metrics(
    *,
    equity_curve: Sequence[float],
    trade_pnls: Sequence[float],
    fees_usd: float,
    slippage_drag_usd: float,
    starting_equity: float,
) -> BacktestMetrics:
    final_eq = equity_curve[-1] if equity_curve else starting_equity
    total_return = 0.0
    if starting_equity > 1e-12:
        total_return = (final_eq - starting_equity) / starting_equity * 100.0

    daily_returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        if prev > 1e-12:
            daily_returns.append((equity_curve[i] - prev) / prev)

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
        sharpe_ratio=_sharpe(daily_returns),
        max_drawdown_pct=_max_drawdown(equity_curve) * 100.0,
        win_rate_pct=win_rate,
        trade_count=trade_count,
        fees_usd=fees_usd,
        slippage_drag_usd=slippage_drag_usd,
        cost_drag_pct=cost_drag * 100.0,
        final_equity=final_eq,
        starting_equity=starting_equity,
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


def compute_verdict(
    metrics: BacktestMetrics,
    *,
    data_ok: bool = True,
    risk_stats: RiskRunStats | None = None,
    allow_micro_live: bool = False,
) -> VerdictResult:
    """Assign tournament verdict; micro_live_candidate disabled unless explicitly allowed."""
    reasons: list[str] = []
    stats = risk_stats or RiskRunStats()
    if not data_ok:
        return VerdictResult("blocked_data", ["missing or invalid OHLCV cache"])

    if metrics.trade_count < MIN_TRADES_FOR_VERDICT:
        return VerdictResult(
            "insufficient_trades",
            [f"trade_count={metrics.trade_count} < {MIN_TRADES_FOR_VERDICT}"],
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
        reasons.append(
            f"return={metrics.total_return_pct:.2f}% dd={metrics.max_drawdown_pct:.2f}%"
        )
        return VerdictResult("kill", reasons)

    if allow_micro_live and metrics.sharpe_ratio > 1.0 and metrics.total_return_pct > 5.0:
        return VerdictResult("micro_live_candidate", ["explicit opt-in only"], micro_live_enabled=True)

    return VerdictResult("paper_candidate", ["meets paper thresholds"])
