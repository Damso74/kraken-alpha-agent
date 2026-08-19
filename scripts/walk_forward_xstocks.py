"""Walk-forward parameter optimization driver for the xStocks backtester.

Workflow
--------
1. Fetch (or load from cache) 240m × 120d OHLC candles for the top-N
   xStocks via :mod:`src.kraken_ohlc_paginated`.
2. Hand the OHLC payload off to :func:`src.walk_forward.run_walk_forward`
   which splits, evaluates a small grid, filters out configs that fail
   the out-of-sample sanity check, and ranks the survivors.
3. Serialize the result to ``data/walk_forward_results.json`` (the
   default — overridable via ``--output``) and print a concise summary.

Hard safety contract
--------------------
- Strictly read-only against the venue. Calls ``kraken ohlc`` only.
- Never invokes ``kraken paper`` / ``kraken order`` / ``kraken futures``
  mutating commands.
- Never mutates ``config.yaml``. The grid overrides flow through a
  cloned :class:`~src.config.Settings` instance.
- The OHLC cache (under ``data/ohlc_cache/``) holds market data only —
  no PnL, no decisions, no credentials.

Usage examples (PowerShell)::

    # Fetch + run with the default grid (≤ 50 combos) and write
    # data/walk_forward_results.json
    python scripts/walk_forward_xstocks.py

    # Re-run from the cached OHLC payload (skips Kraken CLI)
    python scripts/walk_forward_xstocks.py --use-cache-only

    # Smaller grid for development
    python scripts/walk_forward_xstocks.py --quick
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import market_data  # noqa: E402
from src.config import get_settings, reload_settings  # noqa: E402
from src.kraken_ohlc_paginated import (  # noqa: E402
    KRAKEN_OHLC_CAP_PER_CALL,
    OHLCFetchError,
    fetch_ohlc_paginated,
)
from src.logger import get_logger  # noqa: E402
from src.universe import get_universe_tickers, pair_format  # noqa: E402
from src.walk_forward import run_walk_forward  # noqa: E402

logger = get_logger("walk_forward_xstocks")

DEFAULT_INTERVAL_MIN = 240
DEFAULT_TARGET_CANDLES = 720
DEFAULT_OUTPUT = "data/walk_forward_results.json"
DEFAULT_OHLC_CACHE = "data/ohlc_cache/xstocks_{interval}m_{target}.json"

# Walk-forward grid. Designed to stay ≤ 50 combos so the full
# train+test sweep runs in minutes on commodity hardware.
#
# Grid rationale (anchored on the aggressive_competition baseline):
# - ``min_confidence_to_trade``: 0.22 is the active baseline. Sweep
#   ±0.08 to test both more permissive and stricter regimes (4 values).
# - ``min_opportunity_score_buy``: 0.08 is the active baseline.
#   Sweep down to 0.04 (more aggressive) and up to 0.10 (4 values).
# - ``max_hold_minutes``: 90 is the base.exit default. Sweep
#   {60, 90, 180} to test tighter / looser time stops (3 values).
# Total: 4 × 4 × 3 = 48 combos.
DEFAULT_GRID: dict[str, list[Any]] = {
    "min_confidence_to_trade": [0.10, 0.15, 0.22, 0.30],
    "min_opportunity_score_buy": [0.04, 0.06, 0.08, 0.10],
    "max_hold_minutes": [60, 90, 180],
}

# Reduced grid for development / smoke tests.
QUICK_GRID: dict[str, list[Any]] = {
    "min_confidence_to_trade": [0.15, 0.22],
    "min_opportunity_score_buy": [0.06, 0.08],
    "max_hold_minutes": [60, 120],
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Walk-forward parameter optimization for the xStocks "
            "backtester. Strictly read-only — no paper, no live."
        )
    )
    p.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="explicit symbol list (e.g. NVDAx CRCLx HOODx). Falls back to --top.",
    )
    p.add_argument(
        "--top",
        type=int,
        default=9,
        help="top-N symbols from latest ranking when --symbols is absent",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_MIN,
        help="candle interval in minutes (default 240 → ~120 days depth)",
    )
    p.add_argument(
        "--target-candles",
        type=int,
        default=DEFAULT_TARGET_CANDLES,
        help="target candle count per symbol (default 720)",
    )
    p.add_argument(
        "--train-fraction",
        type=float,
        default=0.75,
        help=(
            "train slice fraction (default 0.75 → 540 train candles + "
            "180 test candles when target=720, i.e. 90d train + 30d test "
            "at 240-minute interval)"
        ),
    )
    p.add_argument(
        "--initial-cash",
        type=float,
        default=10_000.0,
        help="starting USD capital",
    )
    p.add_argument(
        "--min-test-pnl-usd",
        type=float,
        default=0.0,
        help="survivor filter: test PnL (USD) must be >= this value",
    )
    p.add_argument(
        "--min-test-win-rate",
        type=float,
        default=0.50,
        help="survivor filter: test win rate must be >= this value",
    )
    p.add_argument(
        "--profile",
        type=str,
        default=None,
        help="override active profile for this run",
    )
    p.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        help=f"output JSON path (default {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--ohlc-cache",
        type=str,
        default=None,
        help=(
            "OHLC cache file path. Defaults to "
            f"{DEFAULT_OHLC_CACHE} with placeholders filled in. "
            "When the file exists it is loaded as-is; when missing it "
            "is created from a fresh Kraken CLI fetch."
        ),
    )
    p.add_argument(
        "--use-cache-only",
        action="store_true",
        help=(
            "fail with a non-zero exit if the OHLC cache is missing "
            "(never call Kraken CLI). Useful for offline replays."
        ),
    )
    p.add_argument(
        "--refresh-cache",
        action="store_true",
        help="force a fresh fetch even when the cache file exists",
    )
    p.add_argument(
        "--quick",
        action="store_true",
        help="use the reduced QUICK_GRID (8 combos) for development",
    )
    p.add_argument(
        "--keep-realtime-cooldown",
        action="store_true",
        help=(
            "do NOT disable the wall-clock cooldown during replay. "
            "Defaults to off because the cooldown clock does not advance "
            "with candles and would block most candidates."
        ),
    )
    return p.parse_args()


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [s.strip() for s in args.symbols if s and s.strip()]
    top_n = max(1, int(args.top or 1))
    latest = ROOT / "data" / "xstocks_rank_latest.json"
    if latest.exists():
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
            rows = payload.get("rows") or []
            ranked: list[str] = []
            for row in rows:
                sym = row.get("symbol") if isinstance(row, dict) else None
                if sym and (row.get("skipped_reason") is None):
                    ranked.append(sym)
                if len(ranked) >= top_n:
                    break
            if ranked:
                return ranked
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read xstocks_rank_latest.json: %s", exc)
    return get_universe_tickers()[:top_n]


def _resolve_cache_path(args: argparse.Namespace) -> Path:
    if args.ohlc_cache:
        candidate = Path(args.ohlc_cache)
    else:
        candidate = Path(
            DEFAULT_OHLC_CACHE.format(
                interval=int(args.interval),
                target=int(args.target_candles),
            )
        )
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    return candidate


def _fetch_ohlc_for_symbols(
    symbols: list[str],
    *,
    interval_minutes: int,
    target_candles: int,
) -> tuple[dict[str, list[dict[str, float]]], dict[str, int]]:
    """Fetch OHLC rows via the paginated helper (with single-call fallback)."""
    quote = get_settings().config.universe.quote
    out: dict[str, list[dict[str, float]]] = {}
    counts: dict[str, int] = {}

    use_pagination = target_candles > KRAKEN_OHLC_CAP_PER_CALL

    for sym in symbols:
        rows: list[dict[str, float]] = []
        if use_pagination:
            try:
                paginated_rows = fetch_ohlc_paginated(
                    pair_format(sym, quote),
                    interval_min=interval_minutes,
                    target_candles=int(target_candles),
                    asset_class="tokenized_asset",
                )
                rows = [r.as_market_data_dict() for r in paginated_rows]
            except OHLCFetchError as exc:
                logger.warning(
                    "paginated OHLC failed for %s, falling back to single-call: %s",
                    sym, exc,
                )
                rows = market_data.get_ohlc(
                    sym, quote,
                    interval_minutes=interval_minutes,
                    count=KRAKEN_OHLC_CAP_PER_CALL,
                )
        else:
            rows = market_data.get_ohlc(
                sym, quote,
                interval_minutes=interval_minutes,
                count=int(target_candles),
            )
        if not isinstance(rows, list):
            rows = []
        out[sym] = rows
        counts[sym] = len(rows)
        logger.info(
            "ohlc %s: %d candles (interval=%dm, paginated=%s)",
            sym, len(rows), interval_minutes, use_pagination,
        )
    return out, counts


def _load_or_fetch_ohlc(
    args: argparse.Namespace,
    symbols: list[str],
) -> tuple[dict[str, list[dict[str, float]]], dict[str, int], Path, str]:
    """Return ``(ohlc_by_symbol, counts, cache_path, provenance)``.

    Provenance is ``"cache"`` when loaded from disk, ``"fetch"`` when
    we hit the Kraken CLI, or ``"cache+fetch"`` if cache existed but a
    refresh was forced.
    """
    cache_path = _resolve_cache_path(args)
    cache_exists = cache_path.exists()

    if cache_exists and not args.refresh_cache:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload_symbols = payload.get("symbols") or []
            ohlc = payload.get("ohlc_by_symbol") or {}
            counts = payload.get("counts") or {}
            # Validate: cache must cover every requested symbol.
            missing = [s for s in symbols if s not in ohlc]
            if not missing:
                logger.info(
                    "loaded OHLC cache from %s (%d symbols)",
                    cache_path, len(payload_symbols),
                )
                return ohlc, counts, cache_path, "cache"
            logger.warning(
                "cache missing symbols %s; refetching",
                ", ".join(missing),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not parse cache %s: %s", cache_path, exc)

    if args.use_cache_only:
        raise SystemExit(
            f"--use-cache-only set but cache {cache_path} is missing or "
            "incomplete; aborting."
        )

    ohlc, counts = _fetch_ohlc_for_symbols(
        symbols,
        interval_minutes=int(args.interval),
        target_candles=int(args.target_candles),
    )
    # Persist the cache (best-effort — failures here are non-fatal).
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "generated_at": _utc_now_iso(),
                    "interval_minutes": int(args.interval),
                    "target_candles": int(args.target_candles),
                    "symbols": symbols,
                    "counts": counts,
                    "ohlc_by_symbol": ohlc,
                },
                default=str,
            ),
            encoding="utf-8",
        )
        logger.info("wrote OHLC cache to %s", cache_path)
    except OSError as exc:
        logger.warning("could not persist OHLC cache to %s: %s", cache_path, exc)

    provenance = "cache+fetch" if cache_exists else "fetch"
    return ohlc, counts, cache_path, provenance


def _utc_now_iso() -> str:
    return (
        datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _iso_from_unix(ts: int | None) -> str | None:
    if ts is None:
        return None
    try:
        return (
            datetime.fromtimestamp(int(ts), tz=UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        return None


def _summarise_candidate(candidate: dict[str, Any] | None) -> str:
    if not candidate:
        return "(none)"
    params = candidate.get("params") or {}
    train = candidate.get("train") or {}
    test = candidate.get("test") or {}
    return (
        f"params={params} | "
        f"train: pnl={train.get('net_pnl_usd', 0):+.2f}$ "
        f"wr={(train.get('win_rate') or 0) * 100:.1f}% "
        f"mdd={train.get('max_drawdown_pct', 0):.2f}% "
        f"trades={train.get('trades_count', 0)} | "
        f"test: pnl={test.get('net_pnl_usd', 0):+.2f}$ "
        f"wr={(test.get('win_rate') or 0) * 100:.1f}% "
        f"mdd={test.get('max_drawdown_pct', 0):.2f}% "
        f"trades={test.get('trades_count', 0)} | "
        f"score={candidate.get('score', 0):+.4f}"
    )


def main() -> int:
    args = _parse_args()
    if args.profile:
        os.environ["KRAKEN_ALPHA_PROFILE"] = args.profile
        reload_settings()

    settings = get_settings()
    profile = settings.active_profile

    symbols = _resolve_symbols(args)
    if not symbols:
        print("No symbols resolved; nothing to walk-forward.")
        return 2

    grid = QUICK_GRID if args.quick else DEFAULT_GRID
    grid_size = 1
    for v in grid.values():
        grid_size *= len(v)

    print(
        f"Walk-forward profile={profile} symbols={symbols} "
        f"interval={args.interval}m target_candles={args.target_candles} "
        f"train_fraction={args.train_fraction} grid={grid_size} combos "
        f"({'quick' if args.quick else 'default'})"
    )

    started = time.time()
    ohlc_by_symbol, counts, cache_path, provenance = _load_or_fetch_ohlc(
        args, symbols
    )
    print(
        f"OHLC ready ({provenance}): cache={cache_path} "
        f"counts={ {s: counts.get(s, 0) for s in symbols} }"
    )

    result = run_walk_forward(
        symbols=symbols,
        ohlc_by_symbol=ohlc_by_symbol,
        grid=grid,
        train_fraction=float(args.train_fraction),
        initial_cash=float(args.initial_cash),
        interval_minutes=int(args.interval),
        min_test_pnl_usd=float(args.min_test_pnl_usd),
        min_test_win_rate=float(args.min_test_win_rate),
        settings=settings,
        disable_realtime_cooldown=not args.keep_realtime_cooldown,
    )

    payload = result.to_dict()
    payload["generated_at"] = _utc_now_iso()
    payload["profile"] = profile
    payload["train_window_iso"] = {
        "first": _iso_from_unix(result.train_first_ts),
        "last": _iso_from_unix(result.train_last_ts),
    }
    payload["test_window_iso"] = {
        "first": _iso_from_unix(result.test_first_ts),
        "last": _iso_from_unix(result.test_last_ts),
    }
    payload["ohlc_cache_path"] = str(cache_path)
    payload["ohlc_provenance"] = provenance
    payload["min_test_pnl_usd"] = float(args.min_test_pnl_usd)
    payload["min_test_win_rate"] = float(args.min_test_win_rate)

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )

    elapsed_total = time.time() - started
    summary_top: list[str] = []
    for c in payload.get("survivors", [])[:10]:
        summary_top.append(_summarise_candidate(c))

    print(
        f"\nWalk-forward complete in {elapsed_total:.2f}s "
        f"(simulation only: {result.elapsed_seconds:.2f}s)."
    )
    print(
        f"train_window: {payload['train_window_iso']['first']} -> "
        f"{payload['train_window_iso']['last']} "
        f"({sum(result.train_candles_per_symbol.values())} candles total)"
    )
    print(
        f"test_window:  {payload['test_window_iso']['first']} -> "
        f"{payload['test_window_iso']['last']} "
        f"({sum(result.test_candles_per_symbol.values())} candles total)"
    )
    print(
        f"grid={result.grid_size} combos, "
        f"survivors={len(result.survivors)} "
        f"(filter test_pnl_usd>={args.min_test_pnl_usd:+.2f} "
        f"and test_win_rate>={args.min_test_win_rate:.2%})"
    )
    winner = payload.get("winner")
    print(f"winner: {_summarise_candidate(winner)}")
    if summary_top:
        print("\nTop survivors (up to 10):")
        for line in summary_top:
            print(f"  - {line}")

    print(f"\nResults JSON: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
