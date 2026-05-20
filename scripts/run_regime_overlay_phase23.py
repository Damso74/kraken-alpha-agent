#!/usr/bin/env python3
"""Regime overlay comparison: standalone vs overlay vs B&H (Phase 23D)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._phase23_common import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    cap_candles,
    run_buy_and_hold,
    run_phase23_cell,
    write_json,
    write_matrix_csv,
)
from src.bot.data_loader import load_ohlcv_candles
from src.bot.phase23_presets import build_phase23_strategy
from src.bot.regime_overlay import RegimeOverlayStrategy
OVERLAY_ASSETS = ("BTC", "ETH")
OVERLAY_TIMEFRAMES = ("1d", "4h")
OVERLAY_STRATEGIES = ("ema_crossover", "donchian_breakout", "trend_following")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 23 regime overlay benchmark")
    p.add_argument("--assets", nargs="+", default=list(OVERLAY_ASSETS))
    p.add_argument("--timeframes", nargs="+", default=list(OVERLAY_TIMEFRAMES))
    p.add_argument("--strategies", nargs="+", default=list(OVERLAY_STRATEGIES))
    p.add_argument("--variant", default="baseline")
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "regime_overlay_phase23",
    )
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--fast", action="store_true")
    p.add_argument(
        "--max-bars",
        type=int,
        default=0,
        help="Cap history length for overlay perf (0=no cap; fast uses 600)",
    )
    return p.parse_args()


def _run_mode(
    mode: str,
    candles: list,
    *,
    sym: str,
    tf: str,
    strategy_name: str,
    variant: str,
    cash: float,
    fees_bps: float,
    slippage_bps: float,
    cache_root: Path,
    data_ok: bool,
    bh_metrics: dict | None,
) -> dict:
    if mode == "buy_and_hold":
        from src.bot.execution_simulator import ExecutionConfig

        exec_cfg = ExecutionConfig(fee_bps=fees_bps, slippage_bps=slippage_bps)
        m = run_buy_and_hold(
            candles,
            symbol=sym,
            cash=cash,
            exec_cfg=exec_cfg,
            timeframe=tf,
            data_ok=data_ok,
        )
        return {
            "mode": mode,
            "asset": sym,
            "timeframe": tf,
            "strategy": "buy_and_hold",
            **m,
        }
    if mode == "standalone":
        return {
            "mode": mode,
            **run_phase23_cell(
                sym,
                tf,
                strategy_name,
                variant,
                "off",
                fees_bps=fees_bps,
                slippage_bps=slippage_bps,
                cash=cash,
                cache_root=cache_root,
                candles=candles,
                data_ok=data_ok,
                bh_metrics=bh_metrics,
            ),
        }
    # regime_overlay
    from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
    from src.bot.journal import BotJournal
    from src.bot.metrics import metrics_to_dict
    from src.bot.paper_engine import run_paper_backtest
    from src.bot.portfolio import PaperPortfolio
    from src.bot.risk_adjusted_metrics import compute_risk_adjusted_bundle
    from src.bot.risk_manager import RiskManager

    inner = build_phase23_strategy(strategy_name, tf, variant)
    wrapped = RegimeOverlayStrategy(inner, tf, cache_regime_features=False)
    exec_cfg = ExecutionConfig(fee_bps=fees_bps, slippage_bps=slippage_bps)
    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    result = run_paper_backtest(
        candles,
        wrapped,
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": tf, "use_classify_verdict": False},
        symbol=sym,
        data_ok=data_ok,
    )
    ra = compute_risk_adjusted_bundle(
        equity_curve=result.equity_curve,
        strategy_return_pct=result.metrics.total_return_pct,
        strategy_max_dd_pct=result.metrics.max_drawdown_pct,
        bh_return_pct=float(bh_metrics.get("total_return_pct", 0.0) if bh_metrics else 0.0),
        bh_max_dd_pct=float(bh_metrics.get("max_drawdown_pct", 0.0) if bh_metrics else 0.0),
        journal=journal,
        warmup_bars=wrapped.warmup_bars(),
        total_bars=len(candles),
    )
    return {
        "mode": "regime_overlay",
        "asset": sym,
        "timeframe": tf,
        "strategy": strategy_name,
        "variant": variant,
        **metrics_to_dict(result.metrics, result.risk_stats),
        **ra,
    }


def main() -> int:
    args = _parse_args()
    if args.fast:
        args.assets = ["BTC"]
        args.timeframes = ["4h"]
        args.strategies = ["ema_crossover"]
        if args.max_bars <= 0:
            args.max_bars = 600
    elif args.max_bars <= 0:
        args.max_bars = 1200

    args.output_dir.mkdir(parents=True, exist_ok=True)
    modes = ("standalone", "regime_overlay", "buy_and_hold")
    runs: list[dict] = []

    for asset in args.assets:
        sym = asset.upper()
        for tf in args.timeframes:
            warmup = 60
            candles, summary = load_ohlcv_candles(
                sym,
                tf,
                args.cache_root,
                cache_only=True,
                warmup_bars=warmup,
            )
            data_ok = summary.status == "available"
            if data_ok:
                candles = cap_candles(candles, args.max_bars)
            bh_metrics = None
            if data_ok:
                from src.bot.execution_simulator import ExecutionConfig

                exec_cfg = ExecutionConfig(
                    fee_bps=args.fees_bps, slippage_bps=args.slippage_bps
                )
                bh_metrics = run_buy_and_hold(
                    candles,
                    symbol=sym,
                    cash=args.cash,
                    exec_cfg=exec_cfg,
                    timeframe=tf,
                    data_ok=True,
                )

            for strategy in args.strategies:
                for mode in modes:
                    if mode == "buy_and_hold" and strategy != args.strategies[0]:
                        continue
                    row = _run_mode(
                        mode,
                        candles if data_ok else [],
                        sym=sym,
                        tf=tf,
                        strategy_name=strategy,
                        variant=args.variant,
                        cash=args.cash,
                        fees_bps=args.fees_bps,
                        slippage_bps=args.slippage_bps,
                        cache_root=args.cache_root,
                        data_ok=data_ok,
                        bh_metrics=bh_metrics,
                    )
                    runs.append(row)

    payload = {
        "phase": 23,
        "axis": "D2_regime_overlay",
        "modes": list(modes),
        "max_bars": args.max_bars,
        "runs": runs,
    }
    write_json(args.output_dir / "results.json", payload)
    write_matrix_csv(args.output_dir / "comparison_matrix.csv", runs)

    print(json.dumps({"output_dir": str(args.output_dir), "runs": len(runs)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
