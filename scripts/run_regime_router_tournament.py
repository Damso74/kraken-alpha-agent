#!/usr/bin/env python3
"""Regime router tournament (Phase 18, cache-only, no live)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_strategy_tournament import PHASE16_STRATEGY_NAMES, _instantiate_strategy
from src.bot.data_loader import load_ohlcv_candles
from src.bot.execution_simulator import ExecutionConfig, ExecutionSimulator
from src.bot.journal import BotJournal
from src.bot.metrics import classify_strategy_verdict, metrics_to_dict
from src.bot.paper_engine import run_paper_backtest
from src.bot.portfolio import PaperPortfolio
from src.bot.regime_classifier import classify_regime
from src.bot.regime_features import compute_regime_features, summarize_regime_features
from src.bot.regime_router import BuyAndHoldStrategy, CashStrategy, RegimeRouterStrategy
from src.bot.risk_manager import RiskManager

MODES = ("regime_router", "best_single", "buy_and_hold", "cash")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Regime router tournament (cache-only)")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH"])
    p.add_argument("--timeframes", nargs="+", default=["1d", "4h", "1h"], choices=["1d", "4h", "1h"])
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "regime_router_phase18",
    )
    p.add_argument("--cache-only", action="store_true", default=True)
    p.add_argument(
        "--cache-root",
        type=Path,
        default=REPO_ROOT / "data" / "collector_cache",
    )
    p.add_argument(
        "--best-single",
        default="trend_following",
        help="Best single strategy label from Phase 17 for comparison",
    )
    p.add_argument(
        "--fast",
        action="store_true",
        help="Phase 22: BTC 4h only, regime_router mode (smoke/benchmark)",
    )
    return p.parse_args()


def _run_mode(
    mode: str,
    candles: list,
    *,
    sym: str,
    tf: str,
    cash: float,
    exec_cfg: ExecutionConfig,
    data_ok: bool,
    best_single: str,
):
    if mode == "regime_router":
        strategy = RegimeRouterStrategy(
            tf,
            available_strategies=PHASE16_STRATEGY_NAMES,
            cache_regime_features=True,
        )
    elif mode == "best_single":
        strategy = _instantiate_strategy(best_single, tf, vol_targeting=False)
    elif mode == "buy_and_hold":
        strategy = BuyAndHoldStrategy()
    else:
        strategy = CashStrategy()

    journal = BotJournal()
    portfolio = PaperPortfolio(cash_usd=cash)
    result = run_paper_backtest(
        candles,
        strategy,
        portfolio,
        RiskManager(),
        ExecutionSimulator(exec_cfg),
        journal,
        {"starting_equity": cash, "timeframe": tf},
        symbol=sym,
        data_ok=data_ok,
    )
    return result, journal, strategy


def main() -> int:
    args = _parse_args()
    if args.fast:
        args.assets = ["BTC"]
        args.timeframes = ["4h"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    exec_cfg = ExecutionConfig(fee_bps=args.fees_bps, slippage_bps=args.slippage_bps)

    results: dict = {
        "phase": 18,
        "modes": list(MODES),
        "best_single_reference": args.best_single,
        "runs": [],
    }
    timeline_rows: list[dict] = []
    equity_rows: list[dict] = []
    trade_rows: list[dict] = []
    decisions: list[dict] = []

    for asset in args.assets:
        sym = asset.upper()
        for tf in args.timeframes:
            warmup = RegimeRouterStrategy(tf).warmup_bars()
            candles, summary = load_ohlcv_candles(
                sym, tf, args.cache_root, cache_only=args.cache_only, warmup_bars=warmup
            )
            data_ok = summary.status == "available"

            for mode in MODES:
                run_id = f"{sym}_{tf}_{mode}"
                if not data_ok:
                    results["runs"].append(
                        {
                            "run_id": run_id,
                            "asset": sym,
                            "timeframe": tf,
                            "mode": mode,
                            "verdict": "blocked_data",
                            "data_ok": False,
                            "blocked_reason": summary.blocked_reason,
                        }
                    )
                    continue

                result, journal, strategy = _run_mode(
                    mode,
                    candles,
                    sym=sym,
                    tf=tf,
                    cash=args.cash,
                    exec_cfg=exec_cfg,
                    data_ok=data_ok,
                    best_single=args.best_single,
                )
                ctx = {
                    "timeframe": tf,
                    "data_ok": data_ok,
                    "risk_stats": result.risk_stats,
                    "candle_count": summary.candle_count,
                    "usable_bars": max(0, summary.candle_count - strategy.warmup_bars()),
                }
                verdict = classify_strategy_verdict(result.metrics, ctx)
                row = {
                    "run_id": run_id,
                    "asset": sym,
                    "timeframe": tf,
                    "mode": mode,
                    "verdict": verdict.verdict,
                    "verdict_reasons": verdict.reasons,
                    "data_ok": data_ok,
                    **metrics_to_dict(result.metrics, result.risk_stats),
                }
                results["runs"].append(row)

                for i, eq in enumerate(result.equity_curve):
                    ts = result.equity_timestamps[i] if i < len(result.equity_timestamps) else i
                    equity_rows.append(
                        {"run_id": run_id, "timestamp": ts, "equity": eq}
                    )

                if journal:
                    for t in journal.trades:
                        t2 = dict(t)
                        t2["run_id"] = run_id
                        trade_rows.append(t2)
                    for d in journal.decisions_as_dicts():
                        d2 = dict(d)
                        d2["run_id"] = run_id
                        decisions.append(d2)

                if mode == "regime_router" and isinstance(strategy, RegimeRouterStrategy):
                    for d in strategy.decision_log:
                        timeline_rows.append({"run_id": run_id, **d})
                    # regime timeline sample every 10 bars
                    for idx in range(strategy.warmup_bars(), len(candles), max(1, len(candles) // 50)):
                        feat = compute_regime_features(candles, idx)
                        if feat:
                            cls = classify_regime(feat)
                            timeline_rows.append(
                                {
                                    "run_id": run_id,
                                    "bar_index": idx,
                                    "regime": cls.regime,
                                    "selected_strategy": route_preview(cls, tf),
                                    "reason": cls.reason,
                                    **summarize_regime_features(feat),
                                }
                            )

    (args.output_dir / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    if timeline_rows:
        with (args.output_dir / "regime_timeline.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            writer = csv.DictWriter(fh, fieldnames=sorted({k for r in timeline_rows for k in r}))
            writer.writeheader()
            writer.writerows(timeline_rows)
    if equity_rows:
        with (args.output_dir / "equity_curve.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            writer = csv.DictWriter(fh, fieldnames=["run_id", "timestamp", "equity"])
            writer.writeheader()
            writer.writerows(equity_rows)
    if trade_rows:
        with (args.output_dir / "trades.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=sorted({k for t in trade_rows for k in t}))
            writer.writeheader()
            writer.writerows(trade_rows)
    with (args.output_dir / "router_decisions.jsonl").open("w", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps(d) + "\n")

    print(json.dumps({"output_dir": str(args.output_dir), "runs": len(results["runs"])}, indent=2))
    return 0


def route_preview(classification, tf: str) -> str:
    from src.bot.regime_router import route_regime

    return route_regime(classification).selected_strategy


if __name__ == "__main__":
    raise SystemExit(main())
