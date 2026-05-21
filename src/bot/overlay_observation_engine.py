"""Phase 28 — overlay paper observation engine (cache-only, no live I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.bot.basis_crowding_overlay import (
    BasisCrowdingOverlayStrategy,
    load_basis_overlay_inputs,
)
from src.bot.daemon_loop import is_duplicate_candle, is_stale_data
from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.overlay_observation_kill import (
    OverlayKillConfig,
    evaluate_overlay_kill,
    observation_stop_active,
    write_observation_stop,
)
from src.bot.overlay_shadow_compare import (
    ShadowComparisonRecord,
    append_shadow_comparison,
    build_shadow_record,
)
from src.bot.paper_engine import _normalize_candles, run_paper_backtest
from src.bot.phase23_presets import build_phase23_strategy
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_manager import RiskManager
from src.bot.state_store import (
    DaemonState,
    PositionState,
    StateBundle,
    append_decision,
    append_equity,
    append_trade,
    load_state,
    log_error,
    save_state,
)

OverlayMode = Literal["funding_basis", "funding_only"]

PHASE28_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("trend_following", "baseline", "funding_basis"),
    ("ema_crossover", "baseline", "funding_basis"),
)


@dataclass(frozen=True)
class ObservationConfig:
    asset: str = "ETH"
    timeframe: str = "4h"
    strategy: str = "trend_following"
    variant: str = "baseline"
    overlay: OverlayMode = "funding_basis"
    state_dir: Path = Path("reports/paper_observation_phase28/trend_following_baseline")
    cache_root: Path = Path("data/collector_cache")
    cash: float = 1000.0
    fees_bps: float = 40.0
    slippage_bps: float = 5.0
    cache_only: bool = True
    observation_only: bool = True


def strategy_state_name(strategy: str, variant: str) -> str:
    return f"{strategy}_{variant}"


def default_state_dir(
    base: Path,
    strategy: str,
    variant: str,
) -> Path:
    return base / strategy_state_name(strategy, variant)


def _build_overlay_strategy(
    asset: str,
    strategy: str,
    variant: str,
    timeframe: str,
    overlay: OverlayMode,
    candles: list,
    cache_root: Path,
) -> tuple[BasisCrowdingOverlayStrategy | None, str]:
    inner = build_phase23_strategy(strategy, timeframe, variant)
    sym = asset.upper().partition("/")[0]
    f_rows, b_rows, status = load_basis_overlay_inputs(sym, timeframe, cache_root)
    if status == "blocked_data":
        return None, "blocked_derivatives"
    mode: OverlayMode = "funding_only" if status == "funding_only" and overlay == "funding_basis" else overlay
    if overlay == "funding_basis" and not b_rows:
        mode = "funding_only"
    inst = BasisCrowdingOverlayStrategy(inner, timeframe, mode=mode)
    inst.bind_derivatives(candles, f_rows, b_rows or [])
    return inst, "available"


def _sync_portfolio(bundle: StateBundle, portfolio: PaperPortfolio, symbol: str) -> None:
    ps = bundle.positions.get(symbol)
    if ps and ps.quantity > 0:
        pos = portfolio.position(symbol)
        pos.quantity = ps.quantity
        pos.avg_entry = ps.avg_entry
        pos.bars_held = ps.bars_held
    portfolio.cash_usd = bundle.state.cash_usd


def _sync_bundle_from_portfolio(
    bundle: StateBundle,
    portfolio: PaperPortfolio,
    symbol: str,
    equity: float,
) -> None:
    pos = portfolio.position(symbol)
    if pos.quantity > 1e-12:
        bundle.positions[symbol] = PositionState(
            symbol=symbol,
            quantity=pos.quantity,
            avg_entry=pos.avg_entry_price,
            bars_held=pos.bars_held,
        )
    elif symbol in bundle.positions:
        del bundle.positions[symbol]
    bundle.state.cash_usd = portfolio.cash_usd
    bundle.state.equity = equity


def run_observation_once(cfg: ObservationConfig) -> dict[str, Any]:
    if observation_stop_active(cfg.state_dir.parent / "STOP_OBSERVATION"):
        return {"status": "stopped", "reason": "STOP_OBSERVATION flag"}

    sym = cfg.asset.upper()
    bundle = load_state(cfg.state_dir)
    if not bundle.state.asset:
        bundle.state = DaemonState(
            asset=sym,
            timeframe=cfg.timeframe,
            strategy=f"{cfg.strategy}+{cfg.overlay}",
            cash_usd=cfg.cash,
            equity=cfg.cash,
            mode="observation_only" if cfg.observation_only else "observation",
        )

    inner = build_phase23_strategy(cfg.strategy, cfg.timeframe, cfg.variant)
    warmup = max(inner.warmup_bars(), 65)

    candles, summary = load_ohlcv_candles(
        sym,
        cfg.timeframe,
        cfg.cache_root,
        cache_only=cfg.cache_only,
        warmup_bars=warmup,
    )
    if summary.status != "available":
        log_error(cfg.state_dir, f"blocked_data: {summary.blocked_reason}")
        return {"status": "blocked_data", "reason": summary.blocked_reason}

    if not candles:
        log_error(cfg.state_dir, "empty candles")
        return {"status": "blocked_data", "reason": "empty"}

    norm_candles = _normalize_candles(candles)

    overlay_inst, deriv_status = _build_overlay_strategy(
        sym,
        cfg.strategy,
        cfg.variant,
        cfg.timeframe,
        cfg.overlay,
        candles,
        cfg.cache_root,
    )
    if overlay_inst is None:
        log_error(cfg.state_dir, deriv_status)
        return {"status": "blocked_data", "reason": deriv_status}

    latest = candles[-1]
    latest_ts = int(latest["timestamp"])
    if is_duplicate_candle(bundle.state.last_processed_timestamp, latest_ts):
        return {"status": "skipped", "reason": "duplicate_candle"}

    stale_deriv = deriv_status == "funding_only" and cfg.overlay == "funding_basis"
    if is_stale_data(bundle.state.last_processed_timestamp, latest_ts):
        log_error(cfg.state_dir, "stale_ohlcv_detected")
        return {"status": "stale_data"}

    bar_index = len(candles) - 1
    portfolio_overlay = PaperPortfolio(cash_usd=bundle.state.cash_usd)
    portfolio_standalone = PaperPortfolio(cash_usd=cfg.cash)
    _sync_portfolio(bundle, portfolio_overlay, sym)

    # Replay to bar_index-1 for signal context
    for i in range(warmup, bar_index):
        portfolio_standalone  # standalone not persisted; shadow only on latest bar

    standalone_sig = inner.on_bar(bar_index, norm_candles, portfolio_standalone, sym)
    overlay_sig = overlay_inst.on_bar(bar_index, norm_candles, portfolio_overlay, sym)
    overlay_state = overlay_inst._state_at(bar_index)

    bh_in_market = portfolio_overlay.position(sym).quantity > 1e-12
    shadow = build_shadow_record(
        timestamp=latest_ts,
        price=float(latest["close"]),
        standalone_sig=standalone_sig,
        overlay_sig=overlay_sig,
        overlay_state=overlay_state,
        bar_index=bar_index,
        warmup=warmup,
        buy_hold_in_market=bh_in_market or bar_index > warmup,
    )
    append_shadow_comparison(cfg.state_dir, shadow)

    exec_cfg = ExecutionConfig(fee_bps=cfg.fees_bps, slippage_bps=cfg.slippage_bps)
    journal = BotJournal()
    result = run_paper_backtest(
        norm_candles,
        overlay_inst,
        portfolio_overlay,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {
            "starting_equity": bundle.state.equity,
            "timeframe": cfg.timeframe,
            "use_classify_verdict": False,
        },
        symbol=sym,
        data_ok=not stale_deriv,
    )

    final_eq = result.metrics.final_equity
    _sync_bundle_from_portfolio(bundle, portfolio_overlay, sym, final_eq)
    bundle.state.last_processed_timestamp = latest_ts
    bundle.state.last_bar_index = bar_index
    bundle.state.iteration += 1
    save_state(cfg.state_dir, bundle)

    append_equity(cfg.state_dir, latest_ts, final_eq)
    decision_record = {
        "timestamp": latest_ts,
        "observation_only": cfg.observation_only,
        "raw_signal": shadow.raw_signal,
        "overlay_decision": shadow.overlay_decision,
        "overlay_reason": shadow.overlay_reason,
        "effective_action": shadow.effective_action,
        "funding_z": shadow.funding_z,
        "basis_z": shadow.basis_z,
        "price": shadow.price,
        "equity": final_eq,
        "derivatives_status": deriv_status,
    }
    append_decision(cfg.state_dir, decision_record)
    for t in journal.trades:
        append_trade(cfg.state_dir, t)

    kill = evaluate_overlay_kill(
        cfg.state_dir,
        config=OverlayKillConfig(stale_data=stale_deriv),
        overlay_equity_curve=result.equity_curve,
        trade_count=result.metrics.trade_count,
        stop_file=cfg.state_dir.parent / "STOP_OBSERVATION",
    )
    if kill.should_kill:
        write_observation_stop(
            cfg.state_dir.parent / "STOP_OBSERVATION",
            "; ".join(kill.reasons),
        )

    return {
        "status": "ok",
        "iteration": bundle.state.iteration,
        "equity": final_eq,
        "trades": result.metrics.trade_count,
        "shadow": decision_record,
        "kill": {"should_kill": kill.should_kill, "reasons": kill.reasons},
        "derivatives_status": deriv_status,
        "observation_only": cfg.observation_only,
    }
