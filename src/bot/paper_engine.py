"""Paper backtest engine — deterministic, no venue I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from .execution_simulator import ExecutionSimulator
from .journal import BotJournal
from .metrics import (
    BacktestMetrics,
    RiskRunStats,
    VerdictResult,
    classify_strategy_verdict,
    compute_metrics,
    compute_verdict,
)
from .orders import Order
from .portfolio import PaperPortfolio
from .risk_manager import RiskManager


@dataclass(frozen=True)
class BotCandle:
    timestamp: str | int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class BacktestResult:
    metrics: BacktestMetrics
    verdict: VerdictResult
    equity_curve: list[float] = field(default_factory=list)
    equity_timestamps: list[str | int] = field(default_factory=list)
    journal: BotJournal | None = None
    symbol: str = ""
    risk_stats: RiskRunStats = field(default_factory=RiskRunStats)


class StrategyProtocol(Protocol):
    name: str

    def warmup_bars(self) -> int: ...

    def on_bar(
        self,
        index: int,
        candles: Sequence[BotCandle],
        portfolio: PaperPortfolio,
        symbol: str,
    ) -> Any: ...


def _candle_ts(c: BotCandle) -> str | int:
    return c.timestamp


def _normalize_candles(candles: Sequence[Any]) -> list[BotCandle]:
    out: list[BotCandle] = []
    for row in candles:
        if isinstance(row, BotCandle):
            out.append(row)
            continue
        if isinstance(row, dict):
            out.append(
                BotCandle(
                    timestamp=row.get("timestamp", row.get("timestamp_utc", 0)),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0.0)),
                )
            )
    return out


def run_paper_backtest(
    candles: Sequence[Any],
    strategy: StrategyProtocol,
    portfolio: PaperPortfolio,
    risk_manager: RiskManager,
    execution_simulator: ExecutionSimulator,
    journal: BotJournal,
    config: Mapping[str, Any] | None = None,
    *,
    symbol: str = "BTC",
    data_ok: bool = True,
) -> BacktestResult:
    """Walk-forward paper simulation on OHLC bars."""
    cfg = dict(config or {})
    bars = _normalize_candles(candles)
    warmup = strategy.warmup_bars()
    equity_curve: list[float] = []
    equity_ts: list[str | int] = []
    trade_pnls: list[float] = []
    slippage_drag = 0.0
    prev_equity = portfolio.cash_usd
    risk_stats = RiskRunStats()
    rules_seen: set[str] = set()
    grid_max_inventory = 0.30
    if getattr(strategy, "name", "") == "grid":
        grid_max_inventory = float(
            getattr(strategy, "max_inventory_fraction", grid_max_inventory)
        )

    for i, bar in enumerate(bars):
        prices = {symbol: bar.close}
        risk_manager.on_bar(equity=portfolio.equity(prices), timestamp=_candle_ts(bar))

        if i < warmup:
            eq = portfolio.equity(prices)
            equity_curve.append(eq)
            equity_ts.append(_candle_ts(bar))
            continue

        signal = strategy.on_bar(i, bars, portfolio, symbol)
        eq = portfolio.equity(prices)
        equity_curve.append(eq)
        equity_ts.append(_candle_ts(bar))

        if signal is None or getattr(signal, "action", "hold") == "hold":
            for pos in portfolio.positions.values():
                if pos.quantity > 1e-12:
                    pos.bars_held += 1
            continue

        action = signal.action
        size_fraction = float(getattr(signal, "size_fraction", 0.0) or 0.0)
        reason = str(getattr(signal, "reason", ""))
        journal.log_signal(
            bar_index=i,
            timestamp=_candle_ts(bar),
            symbol=symbol,
            strategy=strategy.name,
            action=action,
            reason=reason,
            size_fraction=size_fraction,
        )

        if action not in ("buy", "sell"):
            continue

        target_notional = eq * size_fraction
        qty = target_notional / bar.close if bar.close > 1e-12 else 0.0
        pos = portfolio.position(symbol)
        if action == "sell":
            qty = min(qty, pos.quantity)
            if qty <= 1e-12 and pos.quantity > 1e-12:
                qty = pos.quantity

        order = Order(
            symbol=symbol,
            side=action,
            quantity=qty,
            price_hint=bar.close,
            bar_index=i,
            timestamp=_candle_ts(bar),
            strategy=strategy.name,
            reason=reason,
        )

        decision = risk_manager.validate_order(
            order,
            equity=eq,
            cash_usd=portfolio.cash_usd,
            position_fraction=portfolio.position_fraction(symbol, prices),
            exposure_fraction=portfolio.exposure_fraction(prices),
        )
        journal.log_risk(
            bar_index=i,
            timestamp=_candle_ts(bar),
            symbol=symbol,
            decision=decision,
        )
        risk_stats.risk_checks_count += 1
        if decision.verdict == "deny":
            risk_stats.risk_denials_count += 1
            if decision.rule:
                rules_seen.add(decision.rule)
            if decision.rule in ("max_drawdown_pct", "max_daily_loss_pct"):
                risk_stats.stopped_by_risk = True
            continue

        sim = execution_simulator.execute_market(
            order,
            cash_usd=portfolio.cash_usd,
            position_qty=pos.quantity,
        )
        if sim.rejected or sim.fill is None:
            journal.log_reject(
                bar_index=i,
                timestamp=_candle_ts(bar),
                symbol=symbol,
                reason=sim.reject_reason or "rejected",
            )
            continue

        fill = sim.fill
        mid_notional = fill.quantity * order.price_hint
        slip_drag = abs(fill.notional_usd - mid_notional)
        slippage_drag += slip_drag

        eq_before = portfolio.equity(prices)
        portfolio.apply_fill(fill)
        risk_manager.record_trade()
        journal.log_fill(fill)
        eq_after = portfolio.equity(prices)
        trade_pnls.append(eq_after - eq_before)
        prev_equity = eq_after

        for p in portfolio.positions.values():
            if p.quantity > 1e-12:
                p.bars_held += 1

    final_prices = {symbol: bars[-1].close} if bars else {symbol: 0.0}
    if bars:
        exp_frac = portfolio.exposure_fraction(final_prices)
        pos_frac = portfolio.position_fraction(symbol, final_prices)
        if exp_frac < -1e-9 or exp_frac > 1.0 + 1e-6:
            risk_stats.invalid_exposure = True
        if getattr(strategy, "name", "") == "grid" and pos_frac > grid_max_inventory + 1e-6:
            risk_stats.grid_inventory_exceeded = True

    risk_stats.risk_rules_triggered = sorted(rules_seen)
    timeframe = str(cfg.get("timeframe", "1d"))
    candle_count = len(bars)
    usable_bars = max(0, candle_count - warmup)
    metrics = compute_metrics(
        equity_curve=equity_curve,
        trade_pnls=trade_pnls,
        fees_usd=portfolio.fees_paid_usd,
        slippage_drag_usd=slippage_drag,
        starting_equity=float(cfg.get("starting_equity", portfolio.cash_usd)),
        candle_count=candle_count,
        usable_bars=usable_bars,
        timeframe=timeframe,
    )
    if cfg.get("use_classify_verdict", True):
        verdict = classify_strategy_verdict(
            metrics,
            {
                "timeframe": timeframe,
                "data_ok": data_ok,
                "risk_stats": risk_stats,
                "candle_count": candle_count,
                "usable_bars": usable_bars,
            },
        )
        if bool(cfg.get("allow_micro_live", False)) and verdict.verdict == "paper_candidate":
            verdict = compute_verdict(
                metrics,
                data_ok=data_ok,
                risk_stats=risk_stats,
                allow_micro_live=True,
                timeframe=timeframe,
                candle_count=candle_count,
                usable_bars=usable_bars,
            )
    else:
        verdict = compute_verdict(
            metrics,
            data_ok=data_ok,
            risk_stats=risk_stats,
            allow_micro_live=bool(cfg.get("allow_micro_live", False)),
            timeframe=timeframe,
            candle_count=candle_count,
            usable_bars=usable_bars,
        )
    return BacktestResult(
        metrics=metrics,
        verdict=verdict,
        equity_curve=equity_curve,
        equity_timestamps=equity_ts,
        journal=journal,
        symbol=symbol,
        risk_stats=risk_stats,
    )
