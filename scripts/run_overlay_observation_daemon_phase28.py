#!/usr/bin/env python3
"""Phase 28 — ETH 4h funding+basis overlay paper observation daemon (no live orders)."""

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
    release_lock,
    run_daemon_loop,
)
from src.bot.overlay_observation_engine import (
    PHASE28_TARGETS,
    ObservationConfig,
    default_state_dir,
    run_observation_once,
)
from src.bot.state_store import log_error

DEFAULT_BASE = REPO_ROOT / "reports" / "paper_observation_phase28"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ETH 4h overlay paper observation (Phase 28, no live trading)"
    )
    p.add_argument("--asset", default="ETH")
    p.add_argument("--timeframe", default="4h", choices=["4h"])
    p.add_argument("--strategy", default="trend_following")
    p.add_argument("--variant", default="baseline", choices=["baseline", "slow", "fast"])
    p.add_argument(
        "--overlay",
        default="funding_basis",
        choices=["funding_basis", "funding_only"],
    )
    p.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Override state directory (default: reports/paper_observation_phase28/{strategy}_{variant})",
    )
    p.add_argument(
        "--state-base",
        type=Path,
        default=DEFAULT_BASE,
    )
    p.add_argument("--cash", type=float, default=1000.0)
    p.add_argument("--fees-bps", type=float, default=40.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--mode", choices=["once", "loop"], default="once")
    p.add_argument("--interval-seconds", type=float, default=14400.0)
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
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Log decisions only — never route to live execution (default: true)",
    )
    p.add_argument(
        "--run-all-targets",
        action="store_true",
        default=False,
        help="Run both Phase 28 useful overlays sequentially",
    )
    return p.parse_args()


def _build_config(args: argparse.Namespace) -> ObservationConfig:
    state_dir = args.state_dir or default_state_dir(
        args.state_base, args.strategy, args.variant
    )
    return ObservationConfig(
        asset=args.asset,
        timeframe=args.timeframe,
        strategy=args.strategy,
        variant=args.variant,
        overlay=args.overlay,
        state_dir=state_dir,
        cache_root=args.cache_root,
        cash=args.cash,
        fees_bps=args.fees_bps,
        slippage_bps=args.slippage_bps,
        cache_only=args.cache_only,
        observation_only=args.observation_only,
    )


def main() -> int:
    args = _parse_args()
    if args.run_all_targets:
        results: list[dict] = []
        for strategy, variant, overlay in PHASE28_TARGETS:
            args.strategy = strategy
            args.variant = variant
            args.overlay = overlay
            cfg = _build_config(args)
            cfg.state_dir.mkdir(parents=True, exist_ok=True)
            lock = None
            try:
                lock = acquire_lock(cfg.state_dir)
                results.append(run_observation_once(cfg))
            except DaemonLockError as exc:
                results.append({"status": "locked", "strategy": strategy, "error": str(exc)})
            finally:
                if lock is not None:
                    release_lock(lock)
        print(json.dumps({"targets": len(results), "results": results}, indent=2))
        return 0

    cfg = _build_config(args)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    lock = None
    try:
        lock = acquire_lock(cfg.state_dir)
        if args.mode == "once":
            out = run_observation_once(cfg)
            print(json.dumps(out, indent=2))
            return 0

        results: list[dict] = []

        def tick() -> bool:
            try:
                results.append(run_observation_once(cfg))
            except Exception as exc:  # noqa: BLE001 — daemon resilience
                log_error(cfg.state_dir, str(exc))
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
