"""Walk-forward parameter optimisation driver for crypto Perp candidates.

Mirrors :mod:`scripts.walk_forward_xstocks` but routes through the
public REST OHLC endpoint via :mod:`src.crypto_ohlc_rest` (no Kraken
CLI, no PEDSL-CY tokenized_asset block). Targets the five most-liquid
crypto pairs that also have a Perpetual Futures contract:

    XBT/USD, ETH/USD, SOL/USD, AVAX/USD, LTC/USD

Why 240-min × 90 days instead of 60-min × 90 days
-------------------------------------------------
Kraken's public REST OHLC endpoint exposes the same depth wall as the
CLI: at 60-min interval the deepest history we can pull is ~30 days
(720-candle cap, ``since`` cannot reach back further). 240-min is the
natural fit for a 90-day window: ``540`` candles per pair, the entire
2026-02-18 → 2026-05-18 calendar span requested by the brief, no
multi-call hack required. The calendar window matches the user's plan
(train: ~60d / test: ~30d OOS) — only the resolution is coarser.

The 60-min × 30d snapshot is fetched as a side-effect cache so the
operator can run a follow-up sanity check at the live runtime
resolution without re-hitting the network.

Hard safety contract
--------------------
- Strictly read-only against Kraken. Hits ``api.kraken.com/0/public/OHLC``
  and nothing else.
- Never invokes ``kraken paper`` / ``kraken order`` / ``kraken futures``
  mutating commands.
- Never mutates ``config.yaml``. Grid overrides flow through a cloned
  :class:`~src.config.Settings` instance only.
- The OHLC cache (``data/ohlc_cache/crypto/``) holds market data only —
  no PnL, no decisions, no credentials. Already gitignored.

Usage examples (PowerShell)
---------------------------
.. code-block:: powershell

    # Fetch + run the default grid (≤ 60 combos) and write
    # data/walk_forward_crypto_results.json
    .\\.venv\\Scripts\\Activate.ps1
    python scripts/walk_forward_crypto.py

    # Re-run from the cached OHLC payload (skips REST calls)
    python scripts/walk_forward_crypto.py --use-cache-only

    # Smaller grid for development
    python scripts/walk_forward_crypto.py --quick
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings, reload_settings  # noqa: E402
from src.crypto_ohlc_rest import (  # noqa: E402
    CryptoOHLCFetchError,
    fetch_crypto_ohlc_paginated,
    normalize_crypto_pair,
)
from src.logger import get_logger  # noqa: E402
from src.walk_forward import run_walk_forward  # noqa: E402

logger = get_logger("walk_forward_crypto")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS: list[str] = ["BTC", "ETH", "SOL", "AVAX", "LTC"]
DEFAULT_INTERVAL_MIN = 240
DEFAULT_TARGET_CANDLES = 540  # 90 days at 240-min
DEFAULT_OUTPUT = "data/walk_forward_crypto_results.json"
DEFAULT_OHLC_CACHE = "data/ohlc_cache/crypto/crypto_{interval}m_{target}.json"

# Secondary snapshot fetched alongside the main payload. Useful for an
# operator follow-up at the live runtime resolution (60-min).
SECONDARY_INTERVAL_MIN = 60
SECONDARY_TARGET_CANDLES = 720
SECONDARY_CACHE = "data/ohlc_cache/crypto/crypto_{interval}m_{target}.json"

# Train fraction: 540 candles at 240m → ~360 train (60d) + ~180 test (30d).
DEFAULT_TRAIN_FRACTION = 360.0 / 540.0

# Walk-forward grid. Stays ≤ 60 combos so the full train+test sweep
# completes in ≤10 min on commodity hardware. ``time_stop_minutes`` is
# an *alias* of ``max_hold_minutes`` in :mod:`src.exit_rules`
# (``_resolve_params``) — gridding both would double-count the same
# dimension, so we keep ``max_hold_minutes`` as the canonical knob.
DEFAULT_GRID: dict[str, list[Any]] = {
    "min_confidence_to_trade": [0.10, 0.15, 0.20, 0.25],
    "min_opportunity_score_buy": [0.02, 0.04, 0.06],
    "max_hold_minutes": [15, 30, 60, 120],
}  # 4 × 3 × 4 = 48 combos

QUICK_GRID: dict[str, list[Any]] = {
    "min_confidence_to_trade": [0.15, 0.20],
    "min_opportunity_score_buy": [0.04, 0.06],
    "max_hold_minutes": [30, 60],
}  # 2 × 2 × 2 = 8 combos


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Walk-forward parameter optimisation for crypto Perp candidates. "
            "Strictly read-only — no paper, no live."
        )
    )
    p.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help=f"explicit ticker list (default {DEFAULT_SYMBOLS})",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_MIN,
        help="primary candle interval in minutes (default 240 → ~90d depth)",
    )
    p.add_argument(
        "--target-candles",
        type=int,
        default=DEFAULT_TARGET_CANDLES,
        help="target candle count per symbol (default 540 = 90d at 240m)",
    )
    p.add_argument(
        "--secondary-interval",
        type=int,
        default=SECONDARY_INTERVAL_MIN,
        help="secondary cached interval in minutes (default 60 → ~30d snapshot)",
    )
    p.add_argument(
        "--secondary-target-candles",
        type=int,
        default=SECONDARY_TARGET_CANDLES,
        help="target candle count per symbol for the secondary cache",
    )
    p.add_argument(
        "--skip-secondary",
        action="store_true",
        help="do not fetch the secondary 60-min cache",
    )
    p.add_argument(
        "--train-fraction",
        type=float,
        default=DEFAULT_TRAIN_FRACTION,
        help=(
            "train slice fraction (default ~0.667 → 360 train + 180 test "
            "candles at 240-min, i.e. 60d train + 30d test)"
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
        "--min-test-trades-count",
        type=int,
        default=30,
        help=(
            "survivor filter: test set must contain >= this many trades for "
            "the metrics to be statistically meaningful (default 30)"
        ),
    )
    p.add_argument(
        "--profile",
        type=str,
        default=None,
        help=(
            "override active profile for this run (defaults to whatever "
            "config.yaml has set — typically aggressive_competition)"
        ),
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
            "OHLC cache file path (default "
            f"{DEFAULT_OHLC_CACHE} with placeholders filled). When present "
            "the cache is loaded as-is; missing → created via REST."
        ),
    )
    p.add_argument(
        "--use-cache-only",
        action="store_true",
        help="abort with non-zero exit if the cache is missing (offline replay)",
    )
    p.add_argument(
        "--refresh-cache",
        action="store_true",
        help="force a fresh REST fetch even if the cache file exists",
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
            "with replayed candles."
        ),
    )
    return p.parse_args()


def _resolve_cache_path(template: str, *, interval: int, target: int, override: str | None = None) -> Path:
    if override:
        candidate = Path(override)
    else:
        candidate = Path(template.format(interval=int(interval), target=int(target)))
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    return candidate


def _fetch_ohlc_for_symbols(
    symbols: list[str],
    *,
    interval_minutes: int,
    target_candles: int,
) -> tuple[dict[str, list[dict[str, float]]], dict[str, int]]:
    """Fetch OHLC rows via the REST paginated helper."""
    out: dict[str, list[dict[str, float]]] = {}
    counts: dict[str, int] = {}
    for sym in symbols:
        rest_pair = normalize_crypto_pair(sym)
        try:
            paginated_rows = fetch_crypto_ohlc_paginated(
                rest_pair,
                interval_min=int(interval_minutes),
                target_candles=int(target_candles),
            )
            rows = [r.as_market_data_dict() for r in paginated_rows]
        except CryptoOHLCFetchError as exc:
            logger.warning(
                "REST OHLC failed for %s (%s): %s — skipping",
                sym, rest_pair, exc,
            )
            rows = []
        out[sym] = rows
        counts[sym] = len(rows)
        logger.info(
            "crypto ohlc %s (%s): %d candles (interval=%dm)",
            sym, rest_pair, len(rows), interval_minutes,
        )
    return out, counts


def _load_or_fetch_ohlc(
    args: argparse.Namespace,
    symbols: list[str],
    *,
    interval_minutes: int,
    target_candles: int,
    cache_path: Path,
) -> tuple[dict[str, list[dict[str, float]]], dict[str, int], str]:
    """Return ``(ohlc_by_symbol, counts, provenance)`` for one interval."""
    cache_exists = cache_path.exists()
    if cache_exists and not args.refresh_cache:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            ohlc = payload.get("ohlc_by_symbol") or {}
            counts = payload.get("counts") or {}
            missing = [s for s in symbols if s not in ohlc]
            if not missing:
                logger.info(
                    "loaded crypto OHLC cache from %s (%d symbols)",
                    cache_path, len(symbols),
                )
                return ohlc, counts, "cache"
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
        interval_minutes=int(interval_minutes),
        target_candles=int(target_candles),
    )
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "generated_at": _utc_now_iso(),
                    "interval_minutes": int(interval_minutes),
                    "target_candles": int(target_candles),
                    "symbols": symbols,
                    "counts": counts,
                    "ohlc_by_symbol": ohlc,
                    "source": "kraken_public_rest_ohlc",
                },
                default=str,
            ),
            encoding="utf-8",
        )
        logger.info("wrote crypto OHLC cache to %s", cache_path)
    except OSError as exc:
        logger.warning("could not persist crypto OHLC cache to %s: %s", cache_path, exc)
    provenance = "cache+fetch" if cache_exists else "fetch"
    return ohlc, counts, provenance


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _iso_from_unix(ts: int | None) -> str | None:
    if ts is None:
        return None
    try:
        return (
            datetime.fromtimestamp(int(ts), tz=timezone.utc)
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
        import os
        os.environ["KRAKEN_ALPHA_PROFILE"] = args.profile
        reload_settings()

    settings = get_settings()
    profile = settings.active_profile

    symbols = args.symbols or DEFAULT_SYMBOLS
    grid = QUICK_GRID if args.quick else DEFAULT_GRID
    grid_size = 1
    for v in grid.values():
        grid_size *= len(v)

    print(
        f"Walk-forward crypto profile={profile} symbols={symbols} "
        f"interval={args.interval}m target_candles={args.target_candles} "
        f"train_fraction={args.train_fraction:.3f} grid={grid_size} combos "
        f"({'quick' if args.quick else 'default'})"
    )

    started = time.time()
    cache_path = _resolve_cache_path(
        DEFAULT_OHLC_CACHE,
        interval=int(args.interval),
        target=int(args.target_candles),
        override=args.ohlc_cache,
    )
    ohlc_by_symbol, counts, provenance = _load_or_fetch_ohlc(
        args, symbols,
        interval_minutes=int(args.interval),
        target_candles=int(args.target_candles),
        cache_path=cache_path,
    )
    print(
        f"Primary OHLC ready ({provenance}): cache={cache_path} "
        f"counts={ {s: counts.get(s, 0) for s in symbols} }"
    )

    # Secondary cache — read-only side effect for downstream tooling.
    secondary_path = None
    secondary_counts: dict[str, int] = {}
    if not args.skip_secondary:
        secondary_path = _resolve_cache_path(
            SECONDARY_CACHE,
            interval=int(args.secondary_interval),
            target=int(args.secondary_target_candles),
        )
        try:
            _, secondary_counts, sec_provenance = _load_or_fetch_ohlc(
                args, symbols,
                interval_minutes=int(args.secondary_interval),
                target_candles=int(args.secondary_target_candles),
                cache_path=secondary_path,
            )
            print(
                f"Secondary OHLC cached ({sec_provenance}): {secondary_path} "
                f"counts={ {s: secondary_counts.get(s, 0) for s in symbols} }"
            )
        except SystemExit:
            # use-cache-only set and secondary missing — non-fatal.
            print("Secondary cache missing and --use-cache-only set; skipping secondary.")

    result = run_walk_forward(
        symbols=symbols,
        ohlc_by_symbol=ohlc_by_symbol,
        grid=grid,
        train_fraction=float(args.train_fraction),
        initial_cash=float(args.initial_cash),
        interval_minutes=int(args.interval),
        min_test_pnl_usd=float(args.min_test_pnl_usd),
        min_test_win_rate=float(args.min_test_win_rate),
        min_test_trades_count=int(args.min_test_trades_count),
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
    payload["secondary_cache_path"] = str(secondary_path) if secondary_path else None
    payload["secondary_counts"] = secondary_counts
    payload["min_test_pnl_usd"] = float(args.min_test_pnl_usd)
    payload["min_test_win_rate"] = float(args.min_test_win_rate)
    payload["min_test_trades_count"] = int(args.min_test_trades_count)
    payload["asset_class"] = "crypto"
    payload["data_source"] = "kraken_public_rest_ohlc"
    payload["top10_survivors"] = [c for c in payload.get("survivors", [])][:10]

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
        f"AND test_win_rate>={args.min_test_win_rate:.2%} "
        f"AND test_trades>={args.min_test_trades_count})"
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
