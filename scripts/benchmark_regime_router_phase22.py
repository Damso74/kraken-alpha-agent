#!/usr/bin/env python3
"""Phase 22 — regime router benchmark (cache-only, no live)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_strategy_tournament import PHASE16_STRATEGY_NAMES  # noqa: E402
from src.bot.data_loader import load_ohlcv_candles  # noqa: E402
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator  # noqa: E402
from src.bot.journal import BotJournal  # noqa: E402
from src.bot.metrics import classify_strategy_verdict, metrics_to_dict  # noqa: E402
from src.bot.paper_engine import run_paper_backtest  # noqa: E402
from src.bot.portfolio import PaperPortfolio  # noqa: E402
from src.bot.regime_router import RegimeRouterStrategy  # noqa: E402
from src.bot.risk_manager import RiskManager  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark regime router (Phase 22)")
    p.add_argument("--asset", default="BTC")
    p.add_argument("--timeframe", default="4h", choices=["1d", "4h", "1h"])
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "regime_router_perf_phase22",
    )
    p.add_argument(
        "--cache-root",
        type=Path,
        default=REPO_ROOT / "data" / "collector_cache",
    )
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument(
        "--fast",
        action="store_true",
        help="Limit to first 500 bars after warmup (smoke benchmark)",
    )
    return p.parse_args()


def _run_router(
    candles: list,
    *,
    sym: str,
    tf: str,
    cash: float,
    use_cache: bool,
    max_bars: int | None,
) -> dict:
    strategy = RegimeRouterStrategy(
        tf,
        available_strategies=PHASE16_STRATEGY_NAMES,
        cache_regime_features=use_cache,
    )
    subset = candles
    if max_bars is not None:
        warmup = strategy.warmup_bars()
        subset = candles[: warmup + max_bars]

    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    exec_cfg = ExecutionConfig(fee_bps=40.0, slippage_bps=5.0)
    t0 = time.perf_counter()
    result = run_paper_backtest(
        subset,
        strategy,
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": tf},
        symbol=sym,
        data_ok=True,
    )
    elapsed = time.perf_counter() - t0
    ctx = {
        "timeframe": tf,
        "data_ok": True,
        "risk_stats": result.risk_stats,
        "candle_count": len(subset),
        "usable_bars": max(0, len(subset) - strategy.warmup_bars()),
    }
    verdict = classify_strategy_verdict(result.metrics, ctx)
    bars_processed = max(1, len(subset) - strategy.warmup_bars())
    return {
        "use_feature_cache": use_cache,
        "elapsed_sec": round(elapsed, 4),
        "bars_processed": bars_processed,
        "bars_per_sec": round(bars_processed / elapsed, 2) if elapsed > 0 else 0.0,
        "verdict": verdict.verdict,
        **metrics_to_dict(result.metrics, result.risk_stats),
    }


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    sym = args.asset.upper()

    strategy_probe = RegimeRouterStrategy(args.timeframe)
    candles, summary = load_ohlcv_candles(
        sym,
        args.timeframe,
        args.cache_root,
        cache_only=True,
        warmup_bars=strategy_probe.warmup_bars(),
    )
    if summary.status != "available":
        print(json.dumps({"error": summary.blocked_reason}, indent=2))
        return 1

    max_bars = 500 if args.fast else None
    uncached = _run_router(
        candles, sym=sym, tf=args.timeframe, cash=args.cash, use_cache=False, max_bars=max_bars
    )
    cached = _run_router(
        candles, sym=sym, tf=args.timeframe, cash=args.cash, use_cache=True, max_bars=max_bars
    )
    speedup = (
        round(uncached["elapsed_sec"] / cached["elapsed_sec"], 2)
        if cached["elapsed_sec"] > 0
        else 0.0
    )

    payload = {
        "phase": 22,
        "asset": sym,
        "timeframe": args.timeframe,
        "candle_count": summary.candle_count,
        "fast_mode": args.fast,
        "max_bars": max_bars,
        "uncached": uncached,
        "cached": cached,
        "speedup_x": speedup,
        "phase21_gap_filled": f"{sym} {args.timeframe} regime_router (Phase 21 was 1d only)",
    }
    (args.output_dir / "benchmark.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    md = [
        "# Regime router performance — Phase 22",
        "",
        f"Asset/timeframe: **{sym} / {args.timeframe}**",
        f"Candles: {summary.candle_count} (processed {uncached['bars_processed']} bars)",
        "",
        "| Mode | Elapsed (s) | bars/s | Verdict |",
        "|------|-------------|--------|---------|",
        f"| uncached | {uncached['elapsed_sec']} | {uncached['bars_per_sec']} | {uncached['verdict']} |",
        f"| cached | {cached['elapsed_sec']} | {cached['bars_per_sec']} | {cached['verdict']} |",
        "",
        f"**Speedup:** {speedup}x with `cache_regime_features=True`",
        "",
        "> Note: on full BTC 4h runs, speedup ≈1x because inner sub-strategy `on_bar` "
        "dominates; feature precompute removes redundant regime math only.",
        "",
        "## Phase 21 gap",
        "",
        "Phase 21 regime router rerun was **1d only** (17k+ 1h bars too slow uncached).",
        f"This benchmark completes **{args.timeframe}** with feature precompute.",
    ]
    (args.output_dir / "regime_router_perf_phase22.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8"
    )

    print(json.dumps({"output_dir": str(args.output_dir), "speedup_x": speedup}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
