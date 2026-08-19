"""Phase 27 — ETH 4h overlay autopsy metrics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from src.bot.basis_crowding_overlay import classify_eth_overlay_autopsy_verdict
from src.bot.crowding_overlay import CrowdingOverlayStrategy
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.phase23_presets import build_phase23_strategy
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_adjusted_metrics import estimate_time_in_market_pct
from src.bot.risk_manager import RiskManager

ETH4H_AUTOPSY_TARGETS: tuple[tuple[str, str], ...] = (
    ("trend_following", "slow"),
    ("trend_following", "baseline"),
    ("ema_crossover", "baseline"),
)

FEE_SENSITIVITY_BPS: tuple[float, ...] = (0.0, 10.0, 25.0, 40.0)

PERIOD_SPLITS: tuple[tuple[str, int, int], ...] = (
    ("2023", 2023, 2023),
    ("2024", 2024, 2024),
    ("2025_2026", 2025, 2026),
)


def _year_utc(ts: int) -> int:
    return datetime.fromtimestamp(ts, tz=UTC).year


def _slice_candles(candles: Sequence[Mapping[str, Any]], y0: int, y1: int) -> list:
    return [c for c in candles if y0 <= _year_utc(int(c["timestamp"])) <= y1]


def _time_in_market_pct(journal: BotJournal, total_bars: int, *, warmup: int = 0) -> float:
    """Percentage of post-warmup bars with an open position (0..100).

    Thin wrapper over :func:`src.bot.risk_adjusted_metrics.estimate_time_in_market_pct`,
    which returns a *fraction* in ``0..1``; the conversion to percent happens here.
    """
    return (
        estimate_time_in_market_pct(
            journal,
            warmup_bars=max(0, warmup),
            total_bars=total_bars,
        )
        * 100.0
    )


def _missed_upside_pct(
    candles: Sequence[Mapping[str, Any]],
    block_indices: Sequence[int],
    *,
    warmup: int,
) -> float:
    """Sum of forward 4h returns on bars where overlay blocked entry."""
    if not block_indices:
        return 0.0
    total = 0.0
    count = 0
    for idx in block_indices:
        if idx + 1 >= len(candles) or idx < warmup:
            continue
        c0 = float(candles[idx]["close"])
        c1 = float(candles[idx + 1]["close"])
        if c0 > 0:
            total += (c1 / c0 - 1.0) * 100.0
            count += 1
    return total / count if count else 0.0


def _run_overlay_backtest(
    candles: list,
    strategy: str,
    variant: str,
    timeframe: str,
    sym: str,
    *,
    overlay_kind: Literal["crowding", "none"],
    f_rows: list,
    o_rows: list,
    exec_cfg: ExecutionConfig,
    cash: float = 1000.0,
) -> dict[str, Any]:
    inner = build_phase23_strategy(strategy, timeframe, variant)
    if overlay_kind == "crowding":
        inst: Any = CrowdingOverlayStrategy(inner, timeframe)
        inst.bind_derivatives(candles, f_rows, o_rows)
    else:
        inst = inner

    warmup = inst.warmup_bars() if hasattr(inst, "warmup_bars") else inner.warmup_bars()
    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    result = run_paper_backtest(
        candles,
        inst,
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": timeframe, "use_classify_verdict": False},
        symbol=sym,
        data_ok=True,
    )
    metrics = metrics_to_dict(result.metrics, result.risk_stats)
    tim_pct = _time_in_market_pct(journal, len(candles), warmup=warmup)
    block_indices: list[int] = []
    if overlay_kind == "crowding" and hasattr(inst, "_states") and inst._states:
        for i, st in enumerate(inst._states):
            if st.filter == "block":
                block_indices.append(i)
    missed = _missed_upside_pct(candles, block_indices, warmup=warmup)
    return {
        "data_ok": True,
        "total_return_pct": float(metrics.get("total_return_pct", 0)),
        "max_drawdown_pct": float(metrics.get("max_drawdown_pct", 0)),
        "trade_count": int(metrics.get("trade_count", 0)),
        "sharpe_ratio": float(metrics.get("sharpe_ratio", 0)),
        "time_in_market_pct": round(tim_pct, 2),
        "missed_upside_pct": round(missed, 4),
        "fee_bps": exec_cfg.fee_bps,
        "slippage_bps": exec_cfg.slippage_bps,
    }


def run_eth4h_autopsy_cell(
    strategy: str,
    variant: str,
    candles: list,
    *,
    sym: str = "ETH",
    timeframe: str = "4h",
    f_rows: list,
    o_rows: list,
    fee_bps: float = 40.0,
    slippage_bps: float = 5.0,
) -> dict[str, Any]:
    exec_cfg = ExecutionConfig(fee_bps=fee_bps, slippage_bps=slippage_bps)
    baseline = _run_overlay_backtest(
        candles,
        strategy,
        variant,
        timeframe,
        sym,
        overlay_kind="none",
        f_rows=f_rows,
        o_rows=o_rows,
        exec_cfg=exec_cfg,
    )
    overlay = _run_overlay_backtest(
        candles,
        strategy,
        variant,
        timeframe,
        sym,
        overlay_kind="crowding",
        f_rows=f_rows,
        o_rows=o_rows,
        exec_cfg=exec_cfg,
    )

    dd_red = float(baseline["max_drawdown_pct"]) - float(overlay["max_drawdown_pct"])
    trade_delta = int(overlay["trade_count"]) - int(baseline["trade_count"])
    verdict = classify_eth_overlay_autopsy_verdict(
        baseline,
        overlay,
        missed_upside_pct=float(overlay.get("missed_upside_pct", 0)),
    )

    period_rows: list[dict[str, Any]] = []
    inner = build_phase23_strategy(strategy, timeframe, variant)
    warmup = max(inner.warmup_bars(), 65)
    for label, y0, y1 in PERIOD_SPLITS:
        sub = _slice_candles(candles, y0, y1)
        if len(sub) < warmup + 20:
            period_rows.append({"period": label, "skipped": True, "bars": len(sub)})
            continue
        b = _run_overlay_backtest(
            sub,
            strategy,
            variant,
            timeframe,
            sym,
            overlay_kind="none",
            f_rows=f_rows,
            o_rows=o_rows,
            exec_cfg=exec_cfg,
        )
        o = _run_overlay_backtest(
            sub,
            strategy,
            variant,
            timeframe,
            sym,
            overlay_kind="crowding",
            f_rows=f_rows,
            o_rows=o_rows,
            exec_cfg=exec_cfg,
        )
        period_rows.append(
            {
                "period": label,
                "skipped": False,
                "baseline_return_pct": b["total_return_pct"],
                "overlay_return_pct": o["total_return_pct"],
                "dd_reduction_pp": round(
                    float(b["max_drawdown_pct"]) - float(o["max_drawdown_pct"]), 4
                ),
            }
        )

    fee_rows: list[dict[str, Any]] = []
    for fee in FEE_SENSITIVITY_BPS:
        cfg = ExecutionConfig(fee_bps=fee, slippage_bps=slippage_bps)
        b = _run_overlay_backtest(
            candles,
            strategy,
            variant,
            timeframe,
            sym,
            overlay_kind="none",
            f_rows=f_rows,
            o_rows=o_rows,
            exec_cfg=cfg,
        )
        o = _run_overlay_backtest(
            candles,
            strategy,
            variant,
            timeframe,
            sym,
            overlay_kind="crowding",
            f_rows=f_rows,
            o_rows=o_rows,
            exec_cfg=cfg,
        )
        fee_rows.append(
            {
                "fee_bps": fee,
                "baseline_return_pct": b["total_return_pct"],
                "overlay_return_pct": o["total_return_pct"],
                "overlay_still_better_dd": float(o["max_drawdown_pct"])
                < float(b["max_drawdown_pct"]),
            }
        )

    return {
        "asset": sym,
        "timeframe": timeframe,
        "strategy": strategy,
        "variant": variant,
        "baseline": baseline,
        "overlay": overlay,
        "dd_reduction_pp": round(dd_red, 4),
        "trade_count_delta": trade_delta,
        "missed_upside_pct": overlay.get("missed_upside_pct"),
        "time_in_market_baseline_pct": baseline.get("time_in_market_pct"),
        "time_in_market_overlay_pct": overlay.get("time_in_market_pct"),
        "period_stability": period_rows,
        "fee_sensitivity": fee_rows,
        "verdict": verdict,
    }
