"""Phase 25 ultra-strict autopsy for a single Phase 24 validation_candidate."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.phase23_presets import get_phase23_params
from src.bot.phase24_walkforward import (
    classify_phase24_sensitivity_verdict,
    count_holdout_beats_bh,
    create_holdout_sensitivity_plan,
)
from src.bot.portfolio import PaperPortfolio
from src.bot.regime_router import BuyAndHoldStrategy
from src.bot.risk_adjusted_metrics import (
    calmar_like,
    compute_risk_adjusted_bundle,
    drawdown_reduction_vs_bh,
)
from src.bot.risk_manager import RiskManager
from src.bot.walkforward import context_candles_for_period
from src.bot.walkforward_metrics import WindowRunMetrics, aggregate_window_metrics
from src.strategies.presets import STRATEGY_CLASSES

AutopsyVerdict = Literal["kill", "weak", "paper_observation_candidate"]
TestVerdict = Literal["pass", "fail", "warn"]

DEFAULT_CACHE_ROOT = Path(__file__).resolve().parents[2] / "data" / "collector_cache"
DEFAULT_CASH = 1000.0
DEFAULT_FEE_BPS = 40.0
DEFAULT_SLIPPAGE_BPS = 5.0

PHASE24_REFERENCE: dict[str, float | int] = {
    "excess_vs_bh_pct": 0.1388,
    "max_drawdown_pct": 26.66325718745734,
    "bh_max_drawdown_pct": 29.217413920343134,
    "total_return_pct": 4.239252645567672,
    "bh_return_pct": 4.100476971273065,
    "trade_count": 55,
    "holdout_beats_bh": 11,
    "windows_total": 15,
    "bars": 6603,
}

REPRO_TOLERANCE: dict[str, float] = {
    "excess_vs_bh_pct": 0.08,
    "max_drawdown_pct": 0.25,
    "bh_max_drawdown_pct": 0.25,
    "total_return_pct": 0.15,
    "bh_return_pct": 0.15,
}

MIN_DD_REDUCTION_PP = 5.0
TOP3_CONCENTRATION_KILL = 0.50
MIN_PERIODS_POSITIVE_EXCESS = 2


@dataclass(frozen=True)
class CandidateSpec:
    asset: str = "ETH"
    timeframe: str = "4h"
    strategy: str = "trend_following"
    variant: str = "slow"
    overlay: str = "off"
    holdout_pct: float = 0.40
    window_mode: Literal["rolling", "expanding"] = "rolling"

    @property
    def run_id(self) -> str:
        return (
            f"{self.asset}_{self.timeframe}_{self.strategy}_{self.variant}_"
            f"{self.overlay}_h{int(self.holdout_pct * 100)}_{self.window_mode}"
        )


@dataclass
class BacktestSnapshot:
    total_return_pct: float
    bh_return_pct: float
    excess_vs_bh_pct: float
    max_drawdown_pct: float
    bh_max_drawdown_pct: float
    trade_count: int
    sharpe_ratio: float
    turnover_ratio: float
    fee_bps: float
    slippage_bps: float
    holdout_beats_bh: int = 0
    windows_total: int = 0
    bars: int = 0
    calmar_like: float = 0.0
    bh_calmar_like: float = 0.0
    ulcer_index: float = 0.0
    drawdown_reduction_vs_bh: float = 0.0
    max_dd_duration_bars: int = 0
    time_under_water_pct: float = 0.0
    trade_pnls: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    wf_verdict: str = ""
    wf_reason: str = ""


@dataclass
class AutopsyTestResult:
    test_id: str
    verdict: TestVerdict
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


def build_trend_following_instrument(
    timeframe: str,
    variant: str,
    *,
    fast_mult: float = 1.0,
    slow_mult: float = 1.0,
) -> Any:
    params = get_phase23_params("trend_following", timeframe, variant)
    params["fast_period"] = max(2, int(round(float(params["fast_period"]) * fast_mult)))
    params["slow_period"] = max(2, int(round(float(params["slow_period"]) * slow_mult)))
    inst = STRATEGY_CLASSES["trend_following"]()
    for key, value in params.items():
        setattr(inst, key, value)
    return inst


def extract_round_trip_pnls(journal: BotJournal) -> list[float]:
    """Per closed long round-trip PnL (USD) from fill journal."""
    pnls: list[float] = []
    entry_price: float | None = None
    entry_qty: float | None = None
    for t in journal.trades:
        side = str(t.get("side", "")).lower()
        if side == "buy":
            entry_price = float(t.get("price", 0))
            entry_qty = float(t.get("quantity", 0))
        elif side == "sell" and entry_price is not None and entry_qty:
            exit_price = float(t.get("price", 0))
            qty = float(t.get("quantity", 0))
            fee = float(t.get("fee_usd", 0) or 0)
            pnls.append((exit_price - entry_price) * min(qty, entry_qty) - fee)
            entry_price = None
            entry_qty = None
    return pnls


def _underwater_stats(equity_curve: Sequence[float]) -> tuple[int, float]:
    if len(equity_curve) < 2:
        return 0, 0.0
    peak = equity_curve[0]
    duration = 0
    max_duration = 0
    underwater_bars = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
            duration = 0
        elif peak > 1e-12 and eq < peak:
            duration += 1
            underwater_bars += 1
            max_duration = max(max_duration, duration)
    tuw = underwater_bars / max(1, len(equity_curve) - 1) * 100.0
    return max_duration, tuw


def _run_period(
    candles: list,
    strategy: object,
    *,
    sym: str,
    cash: float,
    exec_cfg: ExecutionConfig,
    timeframe: str,
) -> tuple[dict[str, Any], list[float], BotJournal, list[float]]:
    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    result = run_paper_backtest(
        candles,
        strategy,
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": timeframe, "use_classify_verdict": False},
        symbol=sym,
        data_ok=True,
    )
    turnover = 0.0
    if result.metrics.starting_equity > 1e-12 and result.metrics.trade_count > 0:
        traded = sum(
            abs(float(t.get("quantity", 0)) * float(t.get("price", 0)))
            for t in journal.trades
        )
        turnover = traded / result.metrics.starting_equity
    metrics = metrics_to_dict(result.metrics, result.risk_stats)
    metrics["turnover_ratio"] = round(turnover, 4)
    trade_pnls = extract_round_trip_pnls(journal)
    return metrics, result.equity_curve, journal, trade_pnls


def _bh_metrics(
    candles: list,
    *,
    sym: str,
    cash: float,
    exec_cfg: ExecutionConfig,
    timeframe: str,
) -> dict[str, Any]:
    m, _, _, _ = _run_period(
        candles,
        BuyAndHoldStrategy(),
        sym=sym,
        cash=cash,
        exec_cfg=exec_cfg,
        timeframe=timeframe,
    )
    return m


def run_phase24_baseline(
    spec: CandidateSpec,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    cash: float = DEFAULT_CASH,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    candles: list | None = None,
) -> BacktestSnapshot:
    sym = spec.asset.upper()
    instrument = build_trend_following_instrument(spec.timeframe, spec.variant)
    warmup = instrument.warmup_bars()
    if candles is None:
        candles, summary = load_ohlcv_candles(
            sym,
            spec.timeframe,
            cache_root,
            cache_only=True,
            warmup_bars=warmup,
        )
        if summary.status != "available":
            raise RuntimeError(summary.blocked_reason or "data unavailable")

    exec_cfg = ExecutionConfig(fee_bps=fee_bps, slippage_bps=slippage_bps)
    bh_full = _bh_metrics(
        candles,
        sym=sym,
        cash=cash,
        exec_cfg=exec_cfg,
        timeframe=spec.timeframe,
    )
    full_metrics, equity, journal, trade_pnls = _run_period(
        candles,
        instrument,
        sym=sym,
        cash=cash,
        exec_cfg=exec_cfg,
        timeframe=spec.timeframe,
    )

    plan = create_holdout_sensitivity_plan(
        candles,
        spec.timeframe,
        spec.holdout_pct,
        window_mode=spec.window_mode,
    )
    holdout_runs: list[WindowRunMetrics] = []
    validation_runs: list[WindowRunMetrics] = []
    bh_holdout_returns: list[float] = []
    total_trades = 0

    if plan.status == "ok":
        for window in plan.windows:
            ctx_bh = context_candles_for_period(candles, window, "holdout", warmup_bars=1)
            bh_row, _, _, _ = _run_period(
                ctx_bh,
                BuyAndHoldStrategy(),
                sym=sym,
                cash=cash,
                exec_cfg=exec_cfg,
                timeframe=spec.timeframe,
            )
            bh_ret = float(bh_row.get("total_return_pct", 0.0))
            bh_holdout_returns.append(bh_ret)

            for period_name in ("validation", "holdout"):
                ctx = context_candles_for_period(
                    candles, window, period_name, warmup
                )
                metrics_row, _, _, _ = _run_period(
                    ctx,
                    instrument,
                    sym=sym,
                    cash=cash,
                    exec_cfg=exec_cfg,
                    timeframe=spec.timeframe,
                )
                wm = WindowRunMetrics(
                    window_id=window.window_id,
                    period=period_name,
                    net_return_pct=float(metrics_row["total_return_pct"]),
                    max_drawdown_pct=float(metrics_row["max_drawdown_pct"]),
                    trade_count=int(metrics_row["trade_count"]),
                    cost_drag_pct=float(metrics_row.get("cost_drag_pct", 0.0)),
                    sharpe_ratio=float(metrics_row.get("sharpe_ratio", 0.0)),
                )
                if period_name == "holdout":
                    wm.passed = wm.net_return_pct > bh_ret and wm.trade_count >= 1
                    holdout_runs.append(wm)
                    total_trades += wm.trade_count
                else:
                    validation_runs.append(wm)

    agg = aggregate_window_metrics(holdout_runs, validation_runs)
    bh_beats, median_excess = count_holdout_beats_bh(holdout_runs, bh_holdout_returns)
    strat_return = float(full_metrics.get("total_return_pct", 0.0))
    bh_return = float(bh_full.get("total_return_pct", 0.0))
    strat_dd = float(full_metrics.get("max_drawdown_pct", 0.0))
    bh_dd = float(bh_full.get("max_drawdown_pct", 0.0))
    wf = classify_phase24_sensitivity_verdict(
        agg,
        {
            "data_ok": True,
            "plan_status": plan.status,
            "bh_max_drawdown_pct": bh_dd,
            "full_max_drawdown_pct": strat_dd,
            "total_trade_count": total_trades,
            "holdout_beats_bh_count": bh_beats,
            "holdout_bh_windows": len(bh_holdout_returns),
            "median_excess_vs_bh_pct": median_excess,
            "full_excess_vs_bh_pct": strat_return - bh_return,
            "overlay_only_outperformance": spec.overlay != "off",
        },
    )

    ra = compute_risk_adjusted_bundle(
        equity_curve=equity,
        strategy_return_pct=strat_return,
        strategy_max_dd_pct=strat_dd,
        bh_return_pct=bh_return,
        bh_max_dd_pct=bh_dd,
        journal=journal,
        warmup_bars=warmup,
        total_bars=len(candles),
    )
    max_dd_dur, tuw = _underwater_stats(equity)

    return BacktestSnapshot(
        total_return_pct=strat_return,
        bh_return_pct=bh_return,
        excess_vs_bh_pct=round(strat_return - bh_return, 4),
        max_drawdown_pct=strat_dd,
        bh_max_drawdown_pct=bh_dd,
        trade_count=int(full_metrics.get("trade_count", 0)),
        sharpe_ratio=float(full_metrics.get("sharpe_ratio", 0.0)),
        turnover_ratio=float(full_metrics.get("turnover_ratio", 0.0)),
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        holdout_beats_bh=bh_beats,
        windows_total=len(plan.windows) if plan.status == "ok" else 0,
        bars=len(candles),
        calmar_like=calmar_like(strat_return, strat_dd),
        bh_calmar_like=calmar_like(bh_return, bh_dd),
        ulcer_index=float(ra.get("ulcer_index", 0.0)),
        drawdown_reduction_vs_bh=drawdown_reduction_vs_bh(strat_dd, bh_dd),
        max_dd_duration_bars=max_dd_dur,
        time_under_water_pct=round(tuw, 2),
        trade_pnls=trade_pnls,
        equity_curve=list(equity),
        wf_verdict=wf.verdict,
        wf_reason="; ".join(wf.reasons),
    )


def snapshot_to_dict(s: BacktestSnapshot) -> dict[str, Any]:
    return {
        "total_return_pct": s.total_return_pct,
        "bh_return_pct": s.bh_return_pct,
        "excess_vs_bh_pct": s.excess_vs_bh_pct,
        "max_drawdown_pct": s.max_drawdown_pct,
        "bh_max_drawdown_pct": s.bh_max_drawdown_pct,
        "trade_count": s.trade_count,
        "sharpe_ratio": s.sharpe_ratio,
        "turnover_ratio": s.turnover_ratio,
        "fee_bps": s.fee_bps,
        "slippage_bps": s.slippage_bps,
        "holdout_beats_bh": s.holdout_beats_bh,
        "windows_total": s.windows_total,
        "bars": s.bars,
        "calmar_like": s.calmar_like,
        "bh_calmar_like": s.bh_calmar_like,
        "ulcer_index": s.ulcer_index,
        "drawdown_reduction_vs_bh": s.drawdown_reduction_vs_bh,
        "max_dd_duration_bars": s.max_dd_duration_bars,
        "time_under_water_pct": s.time_under_water_pct,
        "wf_verdict": s.wf_verdict,
        "wf_reason": s.wf_reason,
    }


def check_reproducibility(baseline: BacktestSnapshot) -> AutopsyTestResult:
    mismatches: list[str] = []
    for key, ref in PHASE24_REFERENCE.items():
        got = getattr(baseline, key, None)
        if got is None:
            if key in ("bars",):
                got = baseline.bars
            else:
                continue
        tol = REPRO_TOLERANCE.get(key, 0.0)
        if key in ("trade_count", "holdout_beats_bh", "windows_total"):
            if int(got) != int(ref):
                mismatches.append(f"{key}: got {got} ref {ref}")
        elif abs(float(got) - float(ref)) > tol:
            mismatches.append(f"{key}: got {got} ref {ref} tol {tol}")
    if baseline.wf_verdict != "validation_candidate":
        mismatches.append(f"wf_verdict={baseline.wf_verdict}")
    verdict: TestVerdict = "pass" if not mismatches else "fail"
    return AutopsyTestResult(
        "reproducibility",
        verdict,
        "Phase 24 metrics reproduced" if verdict == "pass" else "metric mismatch vs Phase 24",
        {"mismatches": mismatches, "baseline": snapshot_to_dict(baseline)},
    )


def check_param_sensitivity(
    spec: CandidateSpec,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    candles: list | None = None,
) -> AutopsyTestResult:
    sym = spec.asset.upper()
    instrument_base = build_trend_following_instrument(spec.timeframe, spec.variant)
    warmup = instrument_base.warmup_bars()
    if candles is None:
        candles, summary = load_ohlcv_candles(
            sym, spec.timeframe, cache_root, cache_only=True, warmup_bars=warmup
        )
        if summary.status != "available":
            return AutopsyTestResult(
                "param_sensitivity", "fail", "no data", {"reason": summary.blocked_reason}
            )

    exec_cfg = ExecutionConfig(fee_bps=DEFAULT_FEE_BPS, slippage_bps=DEFAULT_SLIPPAGE_BPS)
    bh_full = _bh_metrics(
        candles, sym=sym, cash=DEFAULT_CASH, exec_cfg=exec_cfg, timeframe=spec.timeframe
    )
    bh_ret = float(bh_full.get("total_return_pct", 0.0))
    bh_dd = float(bh_full.get("max_drawdown_pct", 0.0))

    variants = [
        ("fast_m10", 0.9, 1.0),
        ("fast_p10", 1.1, 1.0),
        ("slow_m10", 1.0, 0.9),
        ("slow_p10", 1.0, 1.1),
        ("baseline", 1.0, 1.0),
    ]
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for label, fm, sm in variants:
        inst = build_trend_following_instrument(
            spec.timeframe, spec.variant, fast_mult=fm, slow_mult=sm
        )
        m, _, _, _ = _run_period(
            candles,
            inst,
            sym=sym,
            cash=DEFAULT_CASH,
            exec_cfg=exec_cfg,
            timeframe=spec.timeframe,
        )
        excess = float(m["total_return_pct"]) - bh_ret
        dd = float(m["max_drawdown_pct"])
        ok = excess > 0.0 and (bh_dd <= 1e-9 or dd < bh_dd - 0.5)
        rows.append(
            {
                "label": label,
                "fast_mult": fm,
                "slow_mult": sm,
                "excess_vs_bh_pct": round(excess, 4),
                "max_drawdown_pct": dd,
                "trade_count": m.get("trade_count"),
                "pass": ok,
            }
        )
        if not ok:
            failures.append(label)

    verdict: TestVerdict = "pass" if not failures else "fail"
    return AutopsyTestResult(
        "param_sensitivity",
        verdict,
        "edge survives ±10% param nudges" if verdict == "pass" else "edge fragile to params",
        {"variants": rows, "failures": failures},
    )


def check_fee_sensitivity(
    spec: CandidateSpec,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    candles: list | None = None,
) -> AutopsyTestResult:
    sym = spec.asset.upper()
    instrument = build_trend_following_instrument(spec.timeframe, spec.variant)
    warmup = instrument.warmup_bars()
    if candles is None:
        candles, summary = load_ohlcv_candles(
            sym, spec.timeframe, cache_root, cache_only=True, warmup_bars=warmup
        )
        if summary.status != "available":
            return AutopsyTestResult("fee_sensitivity", "fail", "no data", {})

    fee_grid = [0.0, 10.0, 25.0, 40.0]
    slip_grid = [0.0, 5.0, 10.0]
    rows: list[dict[str, Any]] = []
    only_low_fee_pass = True
    default_pass = False

    for fee in fee_grid:
        for slip in slip_grid:
            exec_cfg = ExecutionConfig(fee_bps=fee, slippage_bps=slip)
            bh = _bh_metrics(
                candles,
                sym=sym,
                cash=DEFAULT_CASH,
                exec_cfg=exec_cfg,
                timeframe=spec.timeframe,
            )
            m, _, _, _ = _run_period(
                candles,
                instrument,
                sym=sym,
                cash=DEFAULT_CASH,
                exec_cfg=exec_cfg,
                timeframe=spec.timeframe,
            )
            excess = float(m["total_return_pct"]) - float(bh["total_return_pct"])
            ok = excess > 0.0
            rows.append(
                {
                    "fee_bps": fee,
                    "slippage_bps": slip,
                    "excess_vs_bh_pct": round(excess, 4),
                    "pass": ok,
                }
            )
            if fee == DEFAULT_FEE_BPS and slip == DEFAULT_SLIPPAGE_BPS:
                default_pass = ok
            if fee >= 25.0 and not ok:
                only_low_fee_pass = False

    verdict: TestVerdict = "pass" if default_pass else "fail"
    summary = (
        "survives default 40bps/5bps slippage"
        if default_pass
        else "fails at default fees — research-only"
    )
    if default_pass and not only_low_fee_pass:
        summary += " (marginal at high fees)"

    return AutopsyTestResult(
        "fee_sensitivity",
        verdict,
        summary,
        {"grid": rows, "default_pass": default_pass, "only_low_fee_edge": only_low_fee_pass},
    )


def _year_utc(ts: int) -> int:
    return datetime.fromtimestamp(ts, tz=UTC).year


def check_period_splits(
    spec: CandidateSpec,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    candles: list | None = None,
) -> AutopsyTestResult:
    sym = spec.asset.upper()
    instrument = build_trend_following_instrument(spec.timeframe, spec.variant)
    warmup = instrument.warmup_bars()
    if candles is None:
        candles, summary = load_ohlcv_candles(
            sym, spec.timeframe, cache_root, cache_only=True, warmup_bars=warmup
        )
        if summary.status != "available":
            return AutopsyTestResult("period_splits", "fail", "no data", {})

    exec_cfg = ExecutionConfig(fee_bps=DEFAULT_FEE_BPS, slippage_bps=DEFAULT_SLIPPAGE_BPS)

    def _slice(y0: int, y1: int) -> list:
        out = []
        for c in candles:
            y = _year_utc(int(c["timestamp"]))
            if y0 <= y <= y1:
                out.append(c)
        return out

    periods = [
        ("2021_2022", 2021, 2022),
        ("2023", 2023, 2023),
        ("2024", 2024, 2024),
        ("2025_2026", 2025, 2026),
    ]
    rows: list[dict[str, Any]] = []
    positive = 0
    for label, y0, y1 in periods:
        sub = _slice(y0, y1)
        if len(sub) < warmup + 50:
            rows.append({"period": label, "bars": len(sub), "skipped": True})
            continue
        bh = _bh_metrics(
            sub, sym=sym, cash=DEFAULT_CASH, exec_cfg=exec_cfg, timeframe=spec.timeframe
        )
        m, _, _, _ = _run_period(
            sub,
            instrument,
            sym=sym,
            cash=DEFAULT_CASH,
            exec_cfg=exec_cfg,
            timeframe=spec.timeframe,
        )
        excess = float(m["total_return_pct"]) - float(bh["total_return_pct"])
        ok = excess > 0.0
        if ok:
            positive += 1
        rows.append(
            {
                "period": label,
                "bars": len(sub),
                "excess_vs_bh_pct": round(excess, 4),
                "trade_count": m.get("trade_count"),
                "pass": ok,
                "skipped": False,
            }
        )

    verdict: TestVerdict = "pass" if positive >= MIN_PERIODS_POSITIVE_EXCESS else "fail"
    return AutopsyTestResult(
        "period_splits",
        verdict,
        f"{positive} periods beat B&H (need {MIN_PERIODS_POSITIVE_EXCESS})",
        {"periods": rows, "positive_periods": positive},
    )


def check_asset_placebo(
    spec: CandidateSpec,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    baseline: BacktestSnapshot | None = None,
) -> AutopsyTestResult:
    targets = [
        ("BTC", "4h"),
        ("SOL", "4h"),
        (spec.asset, "1d"),
    ]
    exec_cfg = ExecutionConfig(fee_bps=DEFAULT_FEE_BPS, slippage_bps=DEFAULT_SLIPPAGE_BPS)
    rows: list[dict[str, Any]] = []
    eth_4h_pass = (
        baseline.excess_vs_bh_pct > 0.0
        if baseline is not None
        else False
    )
    placebo_pass = 0

    for asset, tf in targets:
        inst = build_trend_following_instrument(tf, spec.variant)
        warmup = inst.warmup_bars()
        candles, summary = load_ohlcv_candles(
            asset, tf, cache_root, cache_only=True, warmup_bars=warmup
        )
        if summary.status != "available":
            rows.append({"asset": asset, "timeframe": tf, "skipped": True})
            continue
        bh = _bh_metrics(
            candles,
            sym=asset,
            cash=DEFAULT_CASH,
            exec_cfg=exec_cfg,
            timeframe=tf,
        )
        m, _, _, _ = _run_period(
            candles,
            inst,
            sym=asset,
            cash=DEFAULT_CASH,
            exec_cfg=exec_cfg,
            timeframe=tf,
        )
        excess = float(m["total_return_pct"]) - float(bh["total_return_pct"])
        ok = excess > 0.0
        if ok:
            placebo_pass += 1
        rows.append(
            {
                "asset": asset,
                "timeframe": tf,
                "excess_vs_bh_pct": round(excess, 4),
                "pass": ok,
            }
        )

    if not eth_4h_pass:
        verdict: TestVerdict = "fail"
        summary = "primary ETH 4h does not beat B&H"
    elif placebo_pass == 0:
        verdict = "warn"
        summary = "ETH 4h only — no placebo asset/TF beats B&H"
    else:
        verdict = "pass"
        summary = f"{placebo_pass} placebo cell(s) also beat B&H"
    return AutopsyTestResult(
        "asset_placebo",
        verdict,
        summary,
        {
            "cells": rows,
            "eth_4h_pass": eth_4h_pass,
            "placebo_positive": placebo_pass,
        },
    )


def check_trade_concentration(baseline: BacktestSnapshot) -> AutopsyTestResult:
    pnls = list(baseline.trade_pnls)
    if not pnls:
        return AutopsyTestResult(
            "trade_concentration", "fail", "no round-trip pnls", {}
        )
    abs_total = sum(abs(p) for p in pnls) or 1e-12
    sorted_pnls = sorted(pnls, key=abs, reverse=True)
    top1 = abs(sorted_pnls[0]) / abs_total
    top3 = sum(abs(p) for p in sorted_pnls[:3]) / abs_total

    best = max(pnls)
    worst = min(pnls)
    gross_profit = sum(p for p in pnls if p > 0) or 1e-12
    gross_loss = abs(sum(p for p in pnls if p < 0)) or 1e-12

    verdict: TestVerdict = "pass" if top3 <= TOP3_CONCENTRATION_KILL else "fail"
    return AutopsyTestResult(
        "trade_concentration",
        verdict,
        f"top3 share {top3:.1%}" + (" OK" if verdict == "pass" else " — kill threshold"),
        {
            "top1_pct": round(top1 * 100, 2),
            "top3_pct": round(top3 * 100, 2),
            "trade_count": len(pnls),
            "best_trade_pnl": round(best, 4),
            "worst_trade_pnl": round(worst, 4),
            "gross_profit": round(gross_profit, 4),
            "gross_loss": round(gross_loss, 4),
        },
    )


def check_drawdown_acceptability(baseline: BacktestSnapshot) -> AutopsyTestResult:
    dd_red = baseline.drawdown_reduction_vs_bh
    calmar_adv = baseline.calmar_like > baseline.bh_calmar_like
    significant_dd = dd_red >= MIN_DD_REDUCTION_PP
    marginal_edge = baseline.excess_vs_bh_pct < 0.5 and dd_red < MIN_DD_REDUCTION_PP

    failures: list[str] = []
    if not significant_dd:
        failures.append(f"dd_reduction={dd_red:.2f}pp < {MIN_DD_REDUCTION_PP}")
    if not calmar_adv:
        failures.append("calmar_not_above_bh")
    if marginal_edge:
        failures.append("excess_too_small_for_dd_benefit")

    verdict: TestVerdict = "pass" if not failures else "fail"
    return AutopsyTestResult(
        "drawdown_acceptability",
        verdict,
        "DD materially better than B&H" if verdict == "pass" else "DD benefit insufficient",
        {
            "drawdown_reduction_vs_bh_pp": dd_red,
            "calmar_like": baseline.calmar_like,
            "bh_calmar_like": baseline.bh_calmar_like,
            "ulcer_index": baseline.ulcer_index,
            "max_dd_duration_bars": baseline.max_dd_duration_bars,
            "time_under_water_pct": baseline.time_under_water_pct,
            "excess_vs_bh_pct": baseline.excess_vs_bh_pct,
            "failures": failures,
        },
    )


def classify_final_verdict(
    tests: Sequence[AutopsyTestResult],
) -> AutopsyVerdict:
    by_id = {t.test_id: t for t in tests}
    required_pass = (
        "reproducibility",
        "param_sensitivity",
        "fee_sensitivity",
        "period_splits",
        "trade_concentration",
        "drawdown_acceptability",
    )
    if any(by_id.get(k, AutopsyTestResult(k, "fail", "")).verdict == "fail" for k in required_pass):
        return "kill"
    if by_id.get("asset_placebo", AutopsyTestResult("", "pass", "")).verdict == "warn":
        return "weak"
    if all(by_id.get(k, AutopsyTestResult(k, "fail", "")).verdict == "pass" for k in required_pass):
        return "paper_observation_candidate"
    return "kill"


def run_full_autopsy(
    spec: CandidateSpec | None = None,
    *,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> dict[str, Any]:
    spec = spec or CandidateSpec()
    baseline = run_phase24_baseline(spec, cache_root=cache_root)
    sym = spec.asset.upper()
    candles, _ = load_ohlcv_candles(
        sym,
        spec.timeframe,
        cache_root,
        cache_only=True,
        warmup_bars=build_trend_following_instrument(
            spec.timeframe, spec.variant
        ).warmup_bars(),
    )

    tests = [
        check_reproducibility(baseline),
        check_param_sensitivity(spec, cache_root=cache_root, candles=candles),
        check_fee_sensitivity(spec, cache_root=cache_root, candles=candles),
        check_period_splits(spec, cache_root=cache_root, candles=candles),
        check_asset_placebo(spec, cache_root=cache_root, baseline=baseline),
        check_trade_concentration(baseline),
        check_drawdown_acceptability(baseline),
    ]
    final = classify_final_verdict(tests)
    paper_count = 1 if final == "paper_observation_candidate" else 0

    return {
        "phase": 25,
        "candidate_run_id": spec.run_id,
        "spec": {
            "asset": spec.asset,
            "timeframe": spec.timeframe,
            "strategy": spec.strategy,
            "variant": spec.variant,
            "overlay": spec.overlay,
            "holdout_pct": spec.holdout_pct,
            "window_mode": spec.window_mode,
        },
        "baseline": snapshot_to_dict(baseline),
        "tests": [
            {
                "test_id": t.test_id,
                "verdict": t.verdict,
                "summary": t.summary,
                "details": t.details,
            }
            for t in tests
        ],
        "final_verdict": final,
        "paper_candidate_count": paper_count,
        "paper_observation_candidate_count": paper_count,
        "micro_live": "NO-GO",
    }
