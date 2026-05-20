#!/usr/bin/env python3
"""Paper daemon runner — persistent state, no live orders (Phase 19)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.daemon_loop import (
    DaemonLockError,
    acquire_lock,
    is_duplicate_candle,
    is_stale_data,
    release_lock,
    run_daemon_loop,
)
from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.paper_engine import run_paper_backtest
from src.bot.portfolio import PaperPortfolio
from src.bot.regime_router import RegimeRouterStrategy
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
from src.strategies.presets import build_strategy

REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Paper daemon (no live trading)")
    p.add_argument("--asset", default="BTC")
    p.add_argument("--timeframe", default="1d", choices=["1d", "4h", "1h"])
    p.add_argument("--strategy", default="regime_router")
    p.add_argument(
        "--state-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "paper_daemon_state",
    )
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--mode", choices=["once", "loop"], default="once")
    p.add_argument("--interval-seconds", type=float, default=3600.0)
    p.add_argument("--max-iterations", type=int, default=1)
    p.add_argument("--allow-infinite-loop", action="store_true", default=False)
    p.add_argument("--cache-only", action="store_true", default=True)
    p.add_argument(
        "--cache-root",
        type=Path,
        default=REPO_ROOT / "data" / "collector_cache",
    )
    p.add_argument(
        "--observation-only",
        action="store_true",
        default=False,
        help="Log signals without requiring paper_candidate verdict",
    )
    return p.parse_args()


def _build_strategy(name: str, timeframe: str):
    if name == "regime_router":
        return RegimeRouterStrategy(timeframe)
    return build_strategy(name, timeframe)


def _sync_portfolio(bundle: StateBundle, portfolio: PaperPortfolio, symbol: str) -> None:
    ps = bundle.positions.get(symbol)
    if ps and ps.quantity > 0:
        pos = portfolio.position(symbol)
        pos.quantity = ps.quantity
        pos.avg_entry_price = ps.avg_entry
        pos.bars_held = ps.bars_held
    portfolio.cash_usd = bundle.state.cash_usd


def _sync_bundle_from_portfolio(
    bundle: StateBundle, portfolio: PaperPortfolio, symbol: str, equity: float
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


def run_once(args: argparse.Namespace) -> dict:
    sym = args.asset.upper()
    bundle = load_state(args.state_dir)
    if not bundle.state.asset:
        bundle.state = DaemonState(
            asset=sym,
            timeframe=args.timeframe,
            strategy=args.strategy,
            cash_usd=args.cash,
            equity=args.cash,
            mode="observation_only" if args.observation_only else "observation",
        )

    strategy = _build_strategy(args.strategy, args.timeframe)
    warmup = strategy.warmup_bars()
    candles, summary = load_ohlcv_candles(
        sym,
        args.timeframe,
        args.cache_root,
        cache_only=args.cache_only,
        warmup_bars=warmup,
    )

    if summary.status != "available":
        log_error(args.state_dir, f"blocked_data: {summary.blocked_reason}")
        return {"status": "blocked_data", "reason": summary.blocked_reason}

    if not candles:
        log_error(args.state_dir, "empty candles")
        return {"status": "blocked_data", "reason": "empty"}

    latest = candles[-1]
    latest_ts = int(latest["timestamp"])
    if is_duplicate_candle(bundle.state.last_processed_timestamp, latest_ts):
        return {"status": "skipped", "reason": "duplicate_candle"}

    if is_stale_data(bundle.state.last_processed_timestamp, latest_ts):
        log_error(args.state_dir, "stale_data_detected")
        return {"status": "stale_data"}

    # Process incremental slice since last bar
    start_idx = max(0, bundle.state.last_bar_index + 1)
    if start_idx >= len(candles):
        start_idx = max(warmup, len(candles) - 1)
    slice_candles = candles[: len(candles)]

    portfolio = PaperPortfolio(cash_usd=bundle.state.cash_usd)
    _sync_portfolio(bundle, portfolio, sym)
    exec_cfg = ExecutionConfig(fee_bps=args.fees_bps, slippage_bps=args.slippage_bps)
    journal = BotJournal()

    result = run_paper_backtest(
        slice_candles,
        strategy,
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": bundle.state.equity, "timeframe": args.timeframe},
        symbol=sym,
        data_ok=True,
    )

    final_eq = result.metrics.final_equity
    _sync_bundle_from_portfolio(bundle, portfolio, sym, final_eq)
    bundle.state.last_processed_timestamp = latest_ts
    bundle.state.last_bar_index = len(candles) - 1
    bundle.state.iteration += 1
    save_state(args.state_dir, bundle)

    append_equity(args.state_dir, latest_ts, final_eq)
    if journal:
        for d in journal.decisions_as_dicts():
            append_decision(args.state_dir, d)
        for t in journal.trades:
            append_trade(args.state_dir, t)

    return {
        "status": "ok",
        "iteration": bundle.state.iteration,
        "equity": final_eq,
        "verdict": result.verdict.verdict,
        "trades": result.metrics.trade_count,
    }


def main() -> int:
    args = _parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    lock = None
    try:
        lock = acquire_lock(args.state_dir)
        if args.mode == "once":
            out = run_once(args)
            print(json.dumps(out, indent=2))
            return 0

        results: list[dict] = []

        def tick() -> bool:
            try:
                results.append(run_once(args))
            except Exception as exc:  # noqa: BLE001 — daemon resilience
                log_error(args.state_dir, str(exc))
                results.append({"status": "error", "error": str(exc)})
            return True

        max_iter = args.max_iterations if not args.allow_infinite_loop else 0
        run_daemon_loop(
            tick,
            interval_seconds=args.interval_seconds,
            max_iterations=max_iter,
            allow_infinite=args.allow_infinite_loop,
        )
        print(json.dumps({"iterations": len(results), "results": results}, indent=2))
        return 0
    except DaemonLockError as exc:
        print(json.dumps({"status": "locked", "error": str(exc)}), file=sys.stderr)
        return 1
    finally:
        if lock is not None:
            release_lock(lock)


if __name__ == "__main__":
    raise SystemExit(main())
