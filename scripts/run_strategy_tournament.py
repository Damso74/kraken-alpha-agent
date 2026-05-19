#!/usr/bin/env python3
"""Run strategy tournament on cached OHLCV (Phase 14/15, no live trading)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import classify_strategy_verdict, metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_manager import RiskManager
from src.strategies.presets import STRATEGY_CLASSES, build_strategy
from src.strategies.volatility_targeting import wrap_with_vol_targeting

STRATEGIES = STRATEGY_CLASSES
PHASE16_STRATEGY_NAMES = (
    "trend_following",
    "breakout",
    "mean_reversion",
    "grid",
    "ema_crossover",
    "donchian_breakout",
    "rsi_mean_reversion",
    "bollinger_mean_reversion",
    "atr_breakout",
)


def _load_candles(asset: str, min_rows: int = 60) -> tuple[list[dict], bool]:
    """Phase 14 compatibility — daily cache via data_loader."""
    _ = min_rows
    candles, summary = load_ohlcv_candles(asset, "1d", cache_only=True)
    ok = summary.status == "available"
    return candles, ok


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Paper strategy tournament (cache-only)")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH"])
    p.add_argument("--timeframe", default=None, choices=["1d", "4h", "1h"])
    p.add_argument("--timeframes", nargs="+", default=None, choices=["1d", "4h", "1h"])
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "strategy_tournament_phase16",
    )
    p.add_argument("--cache-only", action="store_true", default=True)
    p.add_argument(
        "--vol-targeting",
        choices=["off", "on"],
        default="off",
        help="Scale buy size_fraction by realized vol overlay (Phase 16)",
    )
    p.add_argument(
        "--phase",
        type=int,
        default=16,
        choices=[15, 16],
        help="Tournament phase label (15 legacy 4-strat, 16 zoo 9-strat)",
    )
    p.add_argument("--min-rows", type=int, default=0, help="legacy; ignored if 0")
    p.add_argument(
        "--cache-root",
        type=Path,
        default=REPO_ROOT / "data" / "collector_cache",
    )
    return p.parse_args()


def _resolve_timeframes(args: argparse.Namespace) -> list[str]:
    if args.timeframes:
        return list(args.timeframes)
    if args.timeframe:
        return [args.timeframe]
    return ["1d"]


def _strategy_names(phase: int) -> tuple[str, ...]:
    if phase <= 15:
        return ("trend_following", "breakout", "mean_reversion", "grid")
    return PHASE16_STRATEGY_NAMES


def _instantiate_strategy(
    strat_name: str,
    tf: str,
    *,
    vol_targeting: bool,
):
    strategy = build_strategy(strat_name, tf)
    if vol_targeting:
        return wrap_with_vol_targeting(strategy, tf)
    return strategy


def main() -> int:
    args = _parse_args()
    timeframes = _resolve_timeframes(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    strategy_names = _strategy_names(args.phase)
    vol_on = args.vol_targeting == "on"

    exec_cfg = ExecutionConfig(fee_bps=args.fees_bps, slippage_bps=args.slippage_bps)
    results: dict = {
        "phase": args.phase,
        "timeframes": timeframes,
        "cash": args.cash,
        "fee_bps": args.fees_bps,
        "slippage_bps": args.slippage_bps,
        "cache_only": bool(args.cache_only),
        "vol_targeting": args.vol_targeting,
        "strategies": list(strategy_names),
        "runs": [],
    }
    all_trades: list[dict] = []
    all_equity: list[dict] = []
    all_decisions: list[dict] = []
    matrix_rows: list[dict] = []

    for asset in args.assets:
        sym = asset.upper()
        for tf in timeframes:
            warmup = 0
            for strat_name in strategy_names:
                strategy = _instantiate_strategy(
                    strat_name, tf, vol_targeting=vol_on
                )
                warmup = max(warmup, strategy.warmup_bars())

            candles, summary = load_ohlcv_candles(
                sym,
                tf,
                args.cache_root,
                cache_only=args.cache_only,
                warmup_bars=warmup,
            )
            data_ok = summary.status == "available"

            for strat_name in strategy_names:
                strategy = _instantiate_strategy(
                    strat_name, tf, vol_targeting=vol_on
                )
                journal = BotJournal()
                portfolio = PaperPortfolio(cash_usd=args.cash)
                result = run_paper_backtest(
                    candles,
                    strategy,
                    portfolio,
                    RiskManager(),
                    ExecutionSimulator(exec_cfg),
                    journal,
                    {"starting_equity": args.cash, "timeframe": tf},
                    symbol=sym,
                    data_ok=data_ok,
                )
                ctx = {
                    "timeframe": tf,
                    "data_ok": data_ok,
                    "risk_stats": result.risk_stats,
                    "candle_count": summary.candle_count,
                    "usable_bars": max(0, summary.candle_count - strategy.warmup_bars()),
                    "blocked_reason": summary.blocked_reason,
                    "enforce_candle_minimum": data_ok,
                }
                result.metrics.candle_count = ctx["candle_count"]
                result.metrics.usable_bars = ctx["usable_bars"]
                verdict = classify_strategy_verdict(result.metrics, ctx)

                run_id = f"{sym}_{tf}_{strat_name}"
                rs = result.risk_stats
                row = {
                    "run_id": run_id,
                    "asset": sym,
                    "timeframe": tf,
                    "strategy": strat_name,
                    "vol_targeting": args.vol_targeting,
                    "verdict": verdict.verdict,
                    "verdict_reasons": verdict.reasons,
                    "data_ok": data_ok,
                    "cache_path": summary.path,
                    "cache_status": summary.status,
                    **metrics_to_dict(result.metrics, rs),
                    "fee_bps": args.fees_bps,
                    "slippage_bps": args.slippage_bps,
                }
                results["runs"].append(row)
                matrix_rows.append(
                    {
                        "asset": sym,
                        "timeframe": tf,
                        "strategy": strat_name,
                        "verdict": verdict.verdict,
                        "total_return_pct": result.metrics.total_return_pct,
                        "trade_count": result.metrics.trade_count,
                        "cost_drag_pct": result.metrics.cost_drag_pct,
                    }
                )

                for i, eq in enumerate(result.equity_curve):
                    ts = (
                        result.equity_timestamps[i]
                        if i < len(result.equity_timestamps)
                        else i
                    )
                    all_equity.append(
                        {
                            "run_id": run_id,
                            "asset": sym,
                            "timeframe": tf,
                            "timestamp": ts,
                            "equity": eq,
                        }
                    )
                if journal:
                    for t in journal.trades:
                        t["run_id"] = run_id
                        t["timeframe"] = tf
                        all_trades.append(t)
                    for d in journal.decisions_as_dicts():
                        d["run_id"] = run_id
                        d["timeframe"] = tf
                        all_decisions.append(d)

    (args.output_dir / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )

    if matrix_rows:
        with (args.output_dir / "results_matrix.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            writer = csv.DictWriter(fh, fieldnames=list(matrix_rows[0].keys()))
            writer.writeheader()
            writer.writerows(matrix_rows)

    if all_trades:
        with (args.output_dir / "trades.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=sorted({k for t in all_trades for k in t}))
            writer.writeheader()
            writer.writerows(all_trades)

    if all_equity:
        with (args.output_dir / "equity_curve.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["run_id", "asset", "timeframe", "timestamp", "equity"],
            )
            writer.writeheader()
            writer.writerows(all_equity)

    with (args.output_dir / "decisions.jsonl").open("w", encoding="utf-8") as fh:
        for d in all_decisions:
            fh.write(json.dumps(d) + "\n")

    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "runs": len(results["runs"]),
                "timeframes": timeframes,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
