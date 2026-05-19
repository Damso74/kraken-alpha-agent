#!/usr/bin/env python3
"""Run Phase 14 strategy tournament on cached OHLCV (no live trading)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.paper_engine import run_paper_backtest
from src.bot.portfolio import PaperPortfolio
from src.bot.risk_manager import RiskManager
from src.data.collectors.binance_public import (
    CollectorError,
    default_ohlc_daily_cache_path,
    load_ohlc_daily_cache,
)
from src.strategies.breakout import BreakoutStrategy
from src.strategies.grid import GridStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.trend_following import TrendFollowingStrategy

STRATEGIES = {
    "trend_following": TrendFollowingStrategy,
    "breakout": BreakoutStrategy,
    "mean_reversion": MeanReversionStrategy,
    "grid": GridStrategy,
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 14 paper strategy tournament")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH"])
    p.add_argument("--timeframe", default="1d", choices=["1d"])
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "strategy_tournament_phase14",
    )
    p.add_argument("--min-rows", type=int, default=60)
    return p.parse_args()


def _load_candles(asset: str, min_rows: int) -> tuple[list[dict], bool]:
    path = default_ohlc_daily_cache_path(asset)
    if not path.is_file():
        return [], False
    end = date.today()
    start = end - timedelta(days=max(min_rows * 2, 365))
    try:
        rows = load_ohlc_daily_cache(path, ticker=asset, start=start, end=end, min_rows=min_rows)
        return rows, True
    except CollectorError:
        return [], False


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    exec_cfg = ExecutionConfig(fee_bps=args.fees_bps, slippage_bps=args.slippage_bps)
    results: dict = {
        "timeframe": args.timeframe,
        "cash": args.cash,
        "fee_bps": args.fees_bps,
        "slippage_bps": args.slippage_bps,
        "runs": [],
    }
    all_trades: list[dict] = []
    all_equity: list[dict] = []
    all_decisions: list[dict] = []

    for asset in args.assets:
        candles, ok = _load_candles(asset.upper(), args.min_rows)
        for strat_name, strat_cls in STRATEGIES.items():
            journal = BotJournal()
            portfolio = PaperPortfolio(cash_usd=args.cash)
            result = run_paper_backtest(
                candles,
                strat_cls(),
                portfolio,
                RiskManager(),
                ExecutionSimulator(exec_cfg),
                journal,
                {"starting_equity": args.cash},
                symbol=asset.upper(),
                data_ok=ok and len(candles) >= args.min_rows,
            )
            run_id = f"{asset}_{strat_name}"
            rs = result.risk_stats
            row = {
                "run_id": run_id,
                "asset": asset.upper(),
                "strategy": strat_name,
                "verdict": result.verdict.verdict,
                "verdict_reasons": result.verdict.reasons,
                "total_return_pct": result.metrics.total_return_pct,
                "sharpe_ratio": result.metrics.sharpe_ratio,
                "max_drawdown_pct": result.metrics.max_drawdown_pct,
                "trade_count": result.metrics.trade_count,
                "fees_usd": result.metrics.fees_usd,
                "slippage_drag_usd": result.metrics.slippage_drag_usd,
                "fee_bps": args.fees_bps,
                "slippage_bps": args.slippage_bps,
                "data_ok": ok and len(candles) >= args.min_rows,
                "risk_denials_count": rs.risk_denials_count,
                "risk_denial_rate": round(rs.risk_denial_rate, 4),
                "risk_rules_triggered": rs.risk_rules_triggered,
                "stopped_by_risk": rs.stopped_by_risk,
            }
            results["runs"].append(row)
            for i, eq in enumerate(result.equity_curve):
                ts = result.equity_timestamps[i] if i < len(result.equity_timestamps) else i
                all_equity.append({"run_id": run_id, "timestamp": ts, "equity": eq})
            if journal:
                for t in journal.trades:
                    t["run_id"] = run_id
                    all_trades.append(t)
                for d in journal.decisions_as_dicts():
                    d["run_id"] = run_id
                    all_decisions.append(d)

    (args.output_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    if all_trades:
        with (args.output_dir / "trades.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=sorted({k for t in all_trades for k in t}))
            writer.writeheader()
            writer.writerows(all_trades)

    if all_equity:
        with (args.output_dir / "equity_curve.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["run_id", "timestamp", "equity"])
            writer.writeheader()
            writer.writerows(all_equity)

    with (args.output_dir / "decisions.jsonl").open("w", encoding="utf-8") as fh:
        for d in all_decisions:
            fh.write(json.dumps(d) + "\n")

    print(json.dumps({"output_dir": str(args.output_dir), "runs": len(results["runs"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
