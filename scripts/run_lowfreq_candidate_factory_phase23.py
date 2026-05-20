#!/usr/bin/env python3
"""Low-frequency trend/breakout candidate factory (Phase 23A/B/C, cache-only)."""

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
    OVERLAY_MODES,
    OverlayMode,
    cap_candles,
    run_phase23_cell,
    write_json,
    write_matrix_csv,
)
from src.bot.data_loader import load_ohlcv_candles
from src.bot.regime_features import precompute_regime_features
from src.bot.phase23_presets import (
    PHASE23_ASSETS,
    PHASE23_LOWFREQ_STRATEGIES,
    PHASE23_TIMEFRAMES,
    PHASE23_VARIANTS,
    build_phase23_strategy,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 23 low-freq candidate factory")
    p.add_argument("--assets", nargs="+", default=list(PHASE23_ASSETS))
    p.add_argument("--timeframes", nargs="+", default=list(PHASE23_TIMEFRAMES))
    p.add_argument("--strategies", nargs="+", default=list(PHASE23_LOWFREQ_STRATEGIES))
    p.add_argument("--variants", nargs="+", default=list(PHASE23_VARIANTS))
    p.add_argument(
        "--overlay",
        nargs="+",
        default=list(OVERLAY_MODES),
        choices=list(OVERLAY_MODES),
    )
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "lowfreq_candidate_factory_phase23",
    )
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    p.add_argument("--fast", action="store_true", help="BTC 1d baseline+off only")
    p.add_argument(
        "--max-bars",
        type=int,
        default=1000,
        help="Evaluation window (last N bars) for factory compute budget; 0=full history",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if args.fast:
        args.assets = ["BTC"]
        args.timeframes = ["1d"]
        args.strategies = ["ema_crossover"]
        args.variants = ["baseline"]
        args.overlay = ["off"]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs: list[dict] = []
    bh_cache: dict[tuple[str, str], dict] = {}

    for asset in args.assets:
        sym = asset.upper()
        for tf in args.timeframes:
            warmup = max(
                build_phase23_strategy(s, tf, "baseline").warmup_bars()
                for s in args.strategies
            )
            candles, summary = load_ohlcv_candles(
                sym,
                tf,
                args.cache_root,
                cache_only=True,
                warmup_bars=warmup,
            )
            data_ok = summary.status == "available"
            if data_ok and args.max_bars > 0:
                candles = cap_candles(candles, args.max_bars)
            regime_precomputed = None
            if data_ok:
                regime_precomputed = precompute_regime_features(candles, ma_window=50)
            bh_key = (sym, tf)
            if data_ok and bh_key not in bh_cache:
                from scripts._phase23_common import run_buy_and_hold
                from src.bot.execution_simulator import ExecutionConfig

                exec_cfg = ExecutionConfig(
                    fee_bps=args.fees_bps, slippage_bps=args.slippage_bps
                )
                bh_cache[bh_key] = run_buy_and_hold(
                    candles,
                    symbol=sym,
                    cash=args.cash,
                    exec_cfg=exec_cfg,
                    timeframe=tf,
                    data_ok=True,
                )

            for strategy in args.strategies:
                for variant in args.variants:
                    for overlay in args.overlay:
                        row = run_phase23_cell(
                            sym,
                            tf,
                            strategy,
                            variant,
                            overlay,  # type: ignore[arg-type]
                            fees_bps=args.fees_bps,
                            slippage_bps=args.slippage_bps,
                            cash=args.cash,
                            cache_root=args.cache_root,
                            candles=candles if data_ok else [],
                            data_ok=data_ok,
                            candle_count=summary.candle_count,
                            bh_metrics=bh_cache.get(bh_key),
                            regime_precomputed=regime_precomputed,
                        )
                        runs.append(row)

    payload = {
        "phase": 23,
        "axis": "A_lowfreq_factory",
        "assets": list(args.assets),
        "timeframes": list(args.timeframes),
        "strategies": list(args.strategies),
        "variants": list(args.variants),
        "overlays": list(args.overlay),
        "fee_bps": args.fees_bps,
        "max_bars": args.max_bars,
        "run_count": len(runs),
        "runs": runs,
    }
    write_json(args.output_dir / "results.json", payload)
    write_matrix_csv(args.output_dir / "results_matrix.csv", runs)

    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "run_count": len(runs),
                "data_ok_runs": sum(1 for r in runs if r.get("data_ok")),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
