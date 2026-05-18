"""Walk-forward parameter optimisation driver for crypto Perp candidates.

Mirrors :mod:`scripts.walk_forward_xstocks` but routes through the
public REST OHLC endpoint via :mod:`src.crypto_ohlc_rest` (no Kraken
CLI, no PEDSL-CY tokenized_asset block). Targets the five most-liquid
crypto pairs that also have a Perpetual Futures contract:

    XBT/USD, ETH/USD, SOL/USD, AVAX/USD, LTC/USD

Three resolution presets (``--grid-preset``)
--------------------------------------------
Kraken's public REST OHLC endpoint caps every call at 720 candles and
``since`` cannot reach back further than the per-interval native depth.
That gives us three natural sweep windows on the same fetcher:

================  =====================  ===================  =================
preset            interval × candles     train / test split   intent
================  =====================  ===================  =================
``default``       240-min × ~540 (90d)   ~60d train / ~30d t  long horizon edge
``60min``         60-min  × ~720 (30d)   ~20d train / ~10d t  intra-day edge
``15min``         15-min  × ~720 (7.5d)  ~5d train / ~2.5d t  scalping edge
================  =====================  ===================  =================

The 60-min and 15-min presets exist because the long-horizon 240-min
sweep returned **0/48 survivors** on 2026-05-18 and we wanted to rule
out an intra-day edge that the coarse resolution might have hidden.

Methodological note on the exit-timer axis
------------------------------------------
``time_stop_minutes`` is the crypto-fast-rotation alias of
``max_hold_minutes`` in :mod:`src.exit_rules` (`_resolve_params`); when
both keys are set on the same override map ``time_stop_minutes`` wins.
Gridding both would silently double-count the same dimension, so each
preset uses **only one** exit-timer key:

- ``default``:  ``max_hold_minutes`` (legacy xStocks knob, kept for
  backward compatibility with the 240-min run already on disk).
- ``60min`` / ``15min``: ``time_stop_minutes`` (the canonical
  crypto-fast-rotation knob — the wider {5..120} range matches the
  brief and is the value the exit-rules engine actually reads).

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

    .\\.venv\\Scripts\\Activate.ps1

    # Long-horizon (default) — 240-min × 90 days, ~60d/30d split.
    python scripts/walk_forward_crypto.py

    # Intra-day — 60-min × 30 days, ~20d/10d split.
    python scripts/walk_forward_crypto.py --grid-preset 60min `
        --output data/walk_forward_crypto_60min_results.json

    # Scalping — 15-min × 7.5 days, ~5d/2.5d split.
    python scripts/walk_forward_crypto.py --grid-preset 15min `
        --output data/walk_forward_crypto_15min_results.json `
        --min-test-trades-count 60 --min-test-win-rate 0.48

    # Re-run from the cached OHLC payload (skips REST calls).
    python scripts/walk_forward_crypto.py --use-cache-only

    # Smaller grid for development.
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
DEFAULT_OUTPUT = "data/walk_forward_crypto_results.json"
DEFAULT_OHLC_CACHE = "data/ohlc_cache/crypto/crypto_{interval}m_{target}.json"

# Per-preset configuration. Each preset bundles every coordinate of the
# walk-forward sweep (resolution, fetch depth, split, grid, OOS filter)
# so the CLI flag stays a single knob and we never silently mix presets.
#
# ``train_fraction`` is the candle-fraction that goes into the train
# set; with 720 candles total a 0.6667 fraction → 480 train + 240 test
# candles. For 60-min × 30d that maps to ~20d/10d; for 15-min × 7.5d
# that maps to ~5d/2.5d. ``train_fraction`` for the legacy ``default``
# preset is 360/540 = 0.6667 (~60d/30d on 240-min × 90d).
PRESETS: dict[str, dict[str, Any]] = {
    "default": {
        "description": "long horizon: 240-min × 90d, ~60d/30d split",
        "interval_minutes": 240,
        "target_candles": 540,
        "train_fraction": 360.0 / 540.0,
        # Legacy xStocks knob, preserved for backward compatibility with
        # ``data/walk_forward_crypto_results.json`` already on disk.
        "grid": {
            "min_confidence_to_trade": [0.10, 0.15, 0.20, 0.25],
            "min_opportunity_score_buy": [0.02, 0.04, 0.06],
            "max_hold_minutes": [15, 30, 60, 120],
        },
        # Filter defaults; CLI flags still override.
        "default_min_test_trades_count": 30,
        "default_min_test_win_rate": 0.50,
        "default_min_test_pnl_usd": 0.0,
        "default_output": "data/walk_forward_crypto_results.json",
    },
    "60min": {
        "description": "intra-day: 60-min × 30d, ~20d/10d split",
        "interval_minutes": 60,
        "target_candles": 720,
        "train_fraction": 480.0 / 720.0,  # 20d train + 10d test
        # ``time_stop_minutes`` = canonical crypto-fast-rotation alias;
        # gridding both axes would double-count the same dimension (the
        # exit-rules engine reads ``time_stop_minutes`` first when set).
        "grid": {
            "min_confidence_to_trade": [0.10, 0.15, 0.20, 0.25],
            "min_opportunity_score_buy": [0.02, 0.04, 0.06],
            "time_stop_minutes": [15, 30, 60, 120],
        },
        "default_min_test_trades_count": 30,
        "default_min_test_win_rate": 0.50,
        "default_min_test_pnl_usd": 0.0,
        "default_output": "data/walk_forward_crypto_60min_results.json",
    },
    "15min": {
        "description": "scalping: 15-min × 7.5d, ~5d/2.5d split",
        "interval_minutes": 15,
        "target_candles": 720,
        "train_fraction": 480.0 / 720.0,  # 5d train + 2.5d test
        # Tighter exit-timer range fits the scalping horizon. Same
        # one-axis-only rule as the 60min preset.
        "grid": {
            "min_confidence_to_trade": [0.10, 0.15, 0.20, 0.25],
            "min_opportunity_score_buy": [0.02, 0.04, 0.06],
            "time_stop_minutes": [5, 15, 30, 60],
        },
        # Slight relaxation on the WR floor (0.48) is justified because
        # 15-min scalping is dominated by mean-reversion on micro
        # ranges; the trade-count floor is bumped to 60 so the sample
        # stays statistically meaningful at the higher fill rate.
        "default_min_test_trades_count": 60,
        "default_min_test_win_rate": 0.48,
        "default_min_test_pnl_usd": 0.0,
        "default_output": "data/walk_forward_crypto_15min_results.json",
    },
}

# Backwards-compatibility shims for downstream callers (e.g. tests,
# importers expecting the legacy module-level constants).
DEFAULT_INTERVAL_MIN = PRESETS["default"]["interval_minutes"]
DEFAULT_TARGET_CANDLES = PRESETS["default"]["target_candles"]
DEFAULT_TRAIN_FRACTION = PRESETS["default"]["train_fraction"]
DEFAULT_GRID: dict[str, list[Any]] = dict(PRESETS["default"]["grid"])

# Secondary snapshot fetched alongside the main payload. Useful for an
# operator follow-up at the live runtime resolution (60-min). Only
# active for the legacy ``default`` preset; the 60min/15min presets
# already have the 60-min depth covered by the primary fetch (60min)
# or are too short to warrant a second pass (15min).
SECONDARY_INTERVAL_MIN = 60
SECONDARY_TARGET_CANDLES = 720
SECONDARY_CACHE = "data/ohlc_cache/crypto/crypto_{interval}m_{target}.json"

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
        "--grid-preset",
        type=str,
        choices=sorted(PRESETS.keys()),
        default="default",
        help=(
            "select a coordinated bundle (interval × candles × split × "
            "grid × filter defaults). 'default'=240m/90d, '60min'=60m/30d, "
            "'15min'=15m/7.5d. Each preset uses a single exit-timer axis "
            "to avoid double-counting (`time_stop_minutes` shadows "
            "`max_hold_minutes` in src.exit_rules)."
        ),
    )
    p.add_argument(
        "--interval",
        type=int,
        default=None,
        help=(
            "override the preset's primary candle interval (minutes). "
            "Rarely needed — the preset already wires this."
        ),
    )
    p.add_argument(
        "--target-candles",
        type=int,
        default=None,
        help="override the preset's target candle count per symbol",
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
        help=(
            "do not fetch the secondary 60-min cache. Auto-skipped for "
            "the 60min and 15min presets (no value-add there)."
        ),
    )
    p.add_argument(
        "--train-fraction",
        type=float,
        default=None,
        help=(
            "override the preset's train slice fraction (default depends "
            "on preset — 0.667 for default/60min/15min)"
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
        default=None,
        help="survivor filter: test PnL (USD) must be >= this value",
    )
    p.add_argument(
        "--min-test-win-rate",
        type=float,
        default=None,
        help=(
            "survivor filter: test win rate must be >= this value "
            "(default 0.50; 15min preset relaxes to 0.48 for scalping)"
        ),
    )
    p.add_argument(
        "--min-test-trades-count",
        type=int,
        default=None,
        help=(
            "survivor filter: test set must contain >= this many trades "
            "(default 30; 15min preset bumps to 60 for fill-rate)"
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
        default=None,
        help=(
            "output JSON path (default depends on preset — "
            "data/walk_forward_crypto_{preset}_results.json)"
        ),
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


def _resolve_preset(args: argparse.Namespace) -> dict[str, Any]:
    """Apply CLI overrides on top of the selected preset and return a
    fully-resolved configuration dict.

    Precedence: CLI flag (when explicit) > preset default. Validates the
    numeric ranges so we fail loud on a typo rather than silently
    fetching an empty page.
    """
    base = PRESETS[args.grid_preset]
    interval = int(args.interval) if args.interval is not None else int(base["interval_minutes"])
    target = int(args.target_candles) if args.target_candles is not None else int(base["target_candles"])
    train_fraction = (
        float(args.train_fraction)
        if args.train_fraction is not None
        else float(base["train_fraction"])
    )
    if interval <= 0:
        raise SystemExit(f"interval must be > 0 (got {interval})")
    if target <= 0:
        raise SystemExit(f"target_candles must be > 0 (got {target})")
    if not (0.0 < train_fraction < 1.0):
        raise SystemExit(
            f"train_fraction must be in (0, 1) (got {train_fraction})"
        )
    return {
        "preset_name": args.grid_preset,
        "description": base["description"],
        "interval_minutes": interval,
        "target_candles": target,
        "train_fraction": train_fraction,
        "grid": dict(base["grid"]),
        "min_test_pnl_usd": (
            float(args.min_test_pnl_usd)
            if args.min_test_pnl_usd is not None
            else float(base["default_min_test_pnl_usd"])
        ),
        "min_test_win_rate": (
            float(args.min_test_win_rate)
            if args.min_test_win_rate is not None
            else float(base["default_min_test_win_rate"])
        ),
        "min_test_trades_count": (
            int(args.min_test_trades_count)
            if args.min_test_trades_count is not None
            else int(base["default_min_test_trades_count"])
        ),
        "output": args.output if args.output else str(base["default_output"]),
    }


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

    resolved = _resolve_preset(args)
    preset_name = resolved["preset_name"]
    interval_minutes = int(resolved["interval_minutes"])
    target_candles = int(resolved["target_candles"])
    train_fraction = float(resolved["train_fraction"])
    min_test_pnl_usd = float(resolved["min_test_pnl_usd"])
    min_test_win_rate = float(resolved["min_test_win_rate"])
    min_test_trades_count = int(resolved["min_test_trades_count"])
    output_path_str = str(resolved["output"])
    grid_from_preset: dict[str, list[Any]] = dict(resolved["grid"])

    symbols = args.symbols or DEFAULT_SYMBOLS
    grid = QUICK_GRID if args.quick else grid_from_preset
    grid_size = 1
    for v in grid.values():
        grid_size *= len(v)

    print(
        f"Walk-forward crypto preset={preset_name} ({resolved['description']}) "
        f"profile={profile} symbols={symbols} "
        f"interval={interval_minutes}m target_candles={target_candles} "
        f"train_fraction={train_fraction:.3f} grid={grid_size} combos "
        f"({'quick' if args.quick else 'preset-grid'})"
    )

    started = time.time()
    cache_path = _resolve_cache_path(
        DEFAULT_OHLC_CACHE,
        interval=interval_minutes,
        target=target_candles,
        override=args.ohlc_cache,
    )
    ohlc_by_symbol, counts, provenance = _load_or_fetch_ohlc(
        args, symbols,
        interval_minutes=interval_minutes,
        target_candles=target_candles,
        cache_path=cache_path,
    )
    print(
        f"Primary OHLC ready ({provenance}): cache={cache_path} "
        f"counts={ {s: counts.get(s, 0) for s in symbols} }"
    )

    # Secondary cache — only meaningful for the legacy ``default``
    # preset (240-min primary + 60-min companion). The 60min preset
    # already has the 60-min depth; the 15min preset would only fetch
    # a redundant 30-day 60-min snapshot, with no value-add.
    secondary_path = None
    secondary_counts: dict[str, int] = {}
    auto_skip_secondary = preset_name in {"60min", "15min"}
    if not args.skip_secondary and not auto_skip_secondary:
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
        train_fraction=train_fraction,
        initial_cash=float(args.initial_cash),
        interval_minutes=interval_minutes,
        min_test_pnl_usd=min_test_pnl_usd,
        min_test_win_rate=min_test_win_rate,
        min_test_trades_count=min_test_trades_count,
        settings=settings,
        disable_realtime_cooldown=not args.keep_realtime_cooldown,
    )

    payload = result.to_dict()
    payload["generated_at"] = _utc_now_iso()
    payload["profile"] = profile
    payload["preset"] = preset_name
    payload["preset_description"] = resolved["description"]
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
    payload["min_test_pnl_usd"] = min_test_pnl_usd
    payload["min_test_win_rate"] = min_test_win_rate
    payload["min_test_trades_count"] = min_test_trades_count
    payload["asset_class"] = "crypto"
    payload["data_source"] = "kraken_public_rest_ohlc"
    payload["top10_survivors"] = [c for c in payload.get("survivors", [])][:10]

    out_path = Path(output_path_str)
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
        f"(filter test_pnl_usd>={min_test_pnl_usd:+.2f} "
        f"AND test_win_rate>={min_test_win_rate:.2%} "
        f"AND test_trades>={min_test_trades_count})"
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
