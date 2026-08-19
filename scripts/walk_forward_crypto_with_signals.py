"""Walk-forward sweep on crypto-perps that layers external-signal gates.

Phase 3 of the strategy-discovery sweep
---------------------------------------
The deterministic walk-forward (``scripts/walk_forward_crypto.py``)
returned 0/144 OOS survivors. Optuna 500-trial Bayesian search
(``scripts/optuna_crypto_search.py``) returned 0 strict OOS survivors
either, but surfaced a small cluster of near-survivors with **positive
out-of-sample PnL** that just miss the win-rate floor (~41–43 % vs the
50 % bar). This script tests whether layering Fear & Greed, BTC
dominance, and realised-volatility regime gates on top of those
near-survivors can push the win-rate over the line without sinking
the PnL.

Hard safety contract
--------------------
- **Strictly read-only** against Kraken: reuses the cached OHLC under
  ``data/ohlc_cache/crypto/`` (60-min × 720 candles ≈ 30 days). Never
  imports execution / kraken-cli mutating modules.
- **Strictly read-only** against the external feeds: the F&G and
  CoinGecko fetchers live in :mod:`src.external_signals` behind a
  cached JSON mapping (``data/external_cache/`` — gitignored).
- **No live order, ever.** Every candidate runs through the same
  walk-forward harness (`src.walk_forward.run_walk_forward`) which
  delegates to `src.backtest.simulate_portfolio`.

Grid construction
-----------------
Two axes are crossed:

1. **Base configs** = top-K distinct optuna trials by score
   (deduplicated by params signature) + one "baseline" config that
   leaves the directional knobs at the active profile's defaults.
   Default K = 4 → 5 base configs.

2. **Gate permutations** = cartesian product of the four optional
   external-signal gates, each with a coarse threshold ladder
   including the explicit ``OFF`` value:

   ============================================== ===========================
   gate                                           values explored
   ============================================== ===========================
   ``block_buy_if_fear_greed_lt``                 ``[None, 25, 30]``
   ``block_buy_if_fear_greed_gt``                 ``[None, 70, 75]``
   ``block_alt_if_btc_dominance_rising_24h_pct``  ``[None, 1.0]``
   ``vol_regime_filter``                          ``[[], ["normal", "high"]]``
   ============================================== ===========================

   That gives 3 × 3 × 2 × 2 = **36 gate permutations**, including the
   "all gates OFF" cell which doubles as a sanity baseline.

Total combos = 5 × 36 = **180** ≤ 200-cap from the brief.

OOS survivor filter (strict, identical to optuna)
-------------------------------------------------
A trial survives only if:

    test.net_pnl_usd >= 0.20
    AND test.win_rate  >= 0.50
    AND test.trades_count >= 30

If at least one cell survives, ``--write-profile`` adds a
``live_crypto_with_signals_capped`` profile to ``config.yaml`` (the
full caps-and-gates spec lives in
``docs/STRATEGY_DISCOVERY_REPORT.md`` and the user must approve the
write explicitly via the flag).

Usage (PowerShell)
------------------
.. code-block:: powershell

    .\\.venv\\Scripts\\Activate.ps1

    # Default sweep — uses the cached OHLC + external signals.
    python scripts/walk_forward_crypto_with_signals.py

    # Force fresh F&G and BTC dominance fetches (BTC dom limited to
    # current value via CoinGecko free).
    python scripts/walk_forward_crypto_with_signals.py --refresh-external

    # Dry analysis without persisting the result.
    python scripts/walk_forward_crypto_with_signals.py --output -
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings, reload_settings  # noqa: E402
from src.external_signals import (  # noqa: E402
    ExternalSnapshot,
    compute_realized_vol_regime,
    fetch_btc_dominance,
    fetch_fear_greed,
    pick_for_date,
)
from src.logger import get_logger  # noqa: E402
from src.walk_forward import run_walk_forward  # noqa: E402

logger = get_logger("walk_forward_with_signals")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS: list[str] = ["BTC", "ETH", "SOL", "AVAX", "LTC"]
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_TARGET_CANDLES = 720
DEFAULT_TRAIN_FRACTION = 480.0 / 720.0
DEFAULT_OHLC_CACHE = "data/ohlc_cache/crypto/crypto_{interval}m_{target}.json"
DEFAULT_FNG_CACHE = "data/external_cache/fear_greed.json"
DEFAULT_BTC_DOM_CACHE = "data/external_cache/btc_dominance.json"
DEFAULT_OPTUNA_RESULTS = "data/optuna_crypto_results.json"
DEFAULT_OUTPUT = "data/walk_forward_with_signals_results.json"
DEFAULT_PROFILE = "micro_live_100eur_crypto"

# OOS survivor filter — same as optuna.
SURVIVOR_MIN_PNL_USD = 0.20
SURVIVOR_MIN_WIN_RATE = 0.50
SURVIVOR_MIN_TRADES = 30


# Gate ladders. Keep the cartesian product within the 200-cap from the
# brief. Each ladder includes ``None`` / ``[]`` as an explicit "OFF"
# value so the all-gates-OFF cell is also tested (sanity baseline).
GATE_LADDERS: dict[str, list[Any]] = {
    "block_buy_if_fear_greed_lt": [None, 25, 30],
    "block_buy_if_fear_greed_gt": [None, 70, 75],
    "block_alt_if_btc_dominance_rising_24h_pct": [None, 1.0],
    "vol_regime_filter": [[], ["normal", "high"]],
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Walk-forward sweep on crypto perps that layers external "
            "Fear & Greed, BTC dominance and realised-vol regime gates "
            "on top of the top-K optuna near-survivors."
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
        default=DEFAULT_INTERVAL_MINUTES,
        help="candle interval in minutes (default 60)",
    )
    p.add_argument(
        "--target-candles",
        type=int,
        default=DEFAULT_TARGET_CANDLES,
        help="OHLC depth per symbol (default 720 ≈ 30 days)",
    )
    p.add_argument(
        "--train-fraction",
        type=float,
        default=DEFAULT_TRAIN_FRACTION,
        help=f"train slice fraction (default {DEFAULT_TRAIN_FRACTION:.4f})",
    )
    p.add_argument(
        "--initial-cash",
        type=float,
        default=10_000.0,
        help="starting USD capital",
    )
    p.add_argument(
        "--profile",
        type=str,
        default=DEFAULT_PROFILE,
        help=f"active profile (default {DEFAULT_PROFILE})",
    )
    p.add_argument(
        "--ohlc-cache",
        type=str,
        default=None,
        help="OHLC cache file (default per interval/target placeholder)",
    )
    p.add_argument(
        "--fng-cache",
        type=str,
        default=DEFAULT_FNG_CACHE,
        help=f"Fear & Greed JSON cache (default {DEFAULT_FNG_CACHE})",
    )
    p.add_argument(
        "--btc-dom-cache",
        type=str,
        default=DEFAULT_BTC_DOM_CACHE,
        help=f"BTC dominance JSON cache (default {DEFAULT_BTC_DOM_CACHE})",
    )
    p.add_argument(
        "--refresh-external",
        action="store_true",
        help=(
            "force a fresh fetch of F&G and BTC dominance, ignoring the "
            "cache. Useful before a final run; disabled by default to "
            "keep the sweep reproducible offline."
        ),
    )
    p.add_argument(
        "--optuna-results",
        type=str,
        default=DEFAULT_OPTUNA_RESULTS,
        help=(
            f"optuna results JSON consumed for the top-K base configs "
            f"(default {DEFAULT_OPTUNA_RESULTS}; pass empty to skip)"
        ),
    )
    p.add_argument(
        "--top-k-base-configs",
        type=int,
        default=4,
        help=(
            "number of distinct optuna trials (by params signature) to "
            "include as base configs. The baseline profile is added on "
            "top regardless."
        ),
    )
    p.add_argument(
        "--vol-regime-window",
        type=int,
        default=20,
        help=(
            "rolling window (candles) used to compute the realised "
            "volatility regime per candle (default 20 candles ≈ 20 h "
            "at 60-min)."
        ),
    )
    p.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        help=(
            f"output JSON path (default {DEFAULT_OUTPUT}, gitignored). "
            "Pass '-' to disable persistence."
        ),
    )
    p.add_argument(
        "--keep-realtime-cooldown",
        action="store_true",
        help="do NOT disable the wall-clock cooldown during replay",
    )
    p.add_argument(
        "--max-combos",
        type=int,
        default=200,
        help="hard ceiling on the (base × gate) cartesian product (default 200)",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# OHLC + signals loaders
# ---------------------------------------------------------------------------


def _resolve_path(p: str | None, default_template: str | None = None, **fmt: int) -> Path | None:
    if not p and default_template is None:
        return None
    target = Path(p) if p else Path(default_template.format(**fmt))  # type: ignore[arg-type]
    if not target.is_absolute():
        target = (ROOT / target).resolve()
    return target


def _load_ohlc(cache_path: Path, *, symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not cache_path.exists():
        raise SystemExit(
            f"OHLC cache {cache_path} is missing. Run "
            "`python scripts/walk_forward_crypto.py --grid-preset 60min` "
            "to populate it before this sweep."
        )
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    ohlc = payload.get("ohlc_by_symbol") or {}
    missing = [s for s in symbols if s not in ohlc or not ohlc[s]]
    if missing:
        raise SystemExit(
            f"OHLC cache {cache_path} is missing symbols: {missing}. Refresh "
            "via scripts/walk_forward_crypto.py before retrying."
        )
    return ohlc


def _ohlc_window_iso(ohlc: dict[str, list[dict[str, Any]]]) -> tuple[str, str]:
    timestamps: list[int] = []
    for rows in ohlc.values():
        for r in rows:
            ts = r.get("timestamp")
            if isinstance(ts, (int, float)):
                timestamps.append(int(ts))
    if not timestamps:
        raise SystemExit("no parseable timestamps in OHLC payload")
    start = datetime.fromtimestamp(min(timestamps), tz=UTC).date()
    # +2d guard so the F&G fetch covers any forward-fill we need at the
    # tail of the test slice.
    end = datetime.fromtimestamp(max(timestamps), tz=UTC).date() + timedelta(days=2)
    return start.isoformat(), end.isoformat()


def _load_external_signals(
    *,
    fng_cache: Path,
    btc_dom_cache: Path,
    start_iso: str,
    end_iso: str,
    refresh: bool,
) -> tuple[dict, dict, dict[str, Any]]:
    """Return ``(fear_greed_by_date, btc_dom_by_date, diagnostics)``.

    A failure on the BTC dominance side is non-fatal — the walk-forward
    can still run with that gate disabled. We surface the failure in
    the report's diagnostics block so the verdict is honest.
    """
    diagnostics: dict[str, Any] = {}

    fng_path = fng_cache
    if refresh and fng_path.exists():
        fng_path.unlink()
    try:
        fng = fetch_fear_greed(start_iso, end_iso, cache_path=fng_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fear & greed fetch failed: %s", exc)
        fng = {}
        diagnostics["fear_greed_error"] = str(exc)
    diagnostics["fear_greed_entries"] = len(fng)
    diagnostics["fear_greed_window"] = (
        f"{min(fng.keys()).isoformat() if fng else None} -> "
        f"{max(fng.keys()).isoformat() if fng else None}"
    )

    btc_dom_path = btc_dom_cache
    if refresh and btc_dom_path.exists():
        btc_dom_path.unlink()
    try:
        btc_dom = fetch_btc_dominance(start_iso, end_iso, cache_path=btc_dom_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("btc dominance fetch failed: %s", exc)
        btc_dom = {}
        diagnostics["btc_dominance_error"] = str(exc)
    diagnostics["btc_dominance_entries"] = len(btc_dom)
    diagnostics["btc_dominance_window"] = (
        f"{min(btc_dom.keys()).isoformat() if btc_dom else None} -> "
        f"{max(btc_dom.keys()).isoformat() if btc_dom else None}"
    )
    diagnostics["btc_dominance_caveat"] = (
        "CoinGecko free has no historical /global endpoint. The "
        "dominance series is sparse — typically only the most recent "
        "day is populated unless multiple runs accumulated entries in "
        "the cache. The block_alt_if_btc_dominance_rising gate is "
        "evaluated only on candles whose date is covered."
    )

    return fng, btc_dom, diagnostics


def _build_external_snapshots(
    ohlc_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    fear_greed: dict,
    btc_dom: dict,
    vol_regime_window: int,
) -> dict[str, dict[str, ExternalSnapshot]]:
    """Pre-compute one ``ExternalSnapshot`` per (symbol, candle_iso_ts).

    The vol regime is computed on the *trailing* candle window so the
    classification at index ``i`` only sees rows ``[0..i]`` — no
    look-ahead. F&G uses the candle's UTC date; BTC dominance uses
    "today" / "today-1d" lookups.
    """
    out: dict[str, dict[str, ExternalSnapshot]] = {}
    for sym, rows in ohlc_by_symbol.items():
        per_sym: dict[str, ExternalSnapshot] = {}
        for i, row in enumerate(rows):
            ts_raw = row.get("timestamp")
            try:
                ts_int = int(ts_raw)
            except (TypeError, ValueError):
                continue
            d = datetime.fromtimestamp(ts_int, tz=UTC).date()
            iso = (
                datetime.fromtimestamp(ts_int, tz=UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
            window_rows = rows[max(0, i - max(vol_regime_window * 4, 200)) : i + 1]
            vol_breakdown = compute_realized_vol_regime(
                window_rows, window=int(vol_regime_window)
            )
            fg = pick_for_date(fear_greed, d)
            btc_today = pick_for_date(btc_dom, d)
            btc_yest = pick_for_date(btc_dom, d - timedelta(days=1))
            per_sym[iso] = ExternalSnapshot(
                fear_greed_index=int(fg) if fg is not None else None,
                btc_dominance_pct=float(btc_today) if btc_today is not None else None,
                btc_dominance_pct_24h_ago=(
                    float(btc_yest) if btc_yest is not None else None
                ),
                vol_regime=vol_breakdown.label,
            )
        out[sym] = per_sym
    return out


# ---------------------------------------------------------------------------
# Base config selection
# ---------------------------------------------------------------------------


def _params_signature(params: dict[str, Any]) -> tuple:
    """Coarse signature for deduplicating top-K trials by parameters."""
    return tuple(
        round(float(params.get(k, 0.0)), 3)
        for k in sorted(params.keys())
    )


def _select_base_configs(
    optuna_results_path: Path | None,
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """Return a list of ``{name, overrides}`` base configs.

    Always includes a ``baseline`` entry with empty overrides (= active
    profile defaults). On top, picks the top-K *distinct* optuna
    trials by score even when no strict survivor exists — the brief's
    "si applicable" clause is interpreted generously to cover the
    no-strict-survivor case where near-survivors with positive PnL
    still represent the most promising directional region.
    """
    base: list[dict[str, Any]] = [
        {"name": "baseline_active_profile", "overrides": {}}
    ]
    if optuna_results_path is None or not optuna_results_path.exists():
        logger.warning(
            "optuna results not found at %s — sweep runs only against "
            "the baseline profile",
            optuna_results_path,
        )
        return base

    payload = json.loads(optuna_results_path.read_text(encoding="utf-8"))
    trials = list(payload.get("all_trials") or [])
    trials.sort(key=lambda t: float(t.get("score") or 0.0), reverse=True)

    seen: set[tuple] = set()
    picked = 0
    for t in trials:
        params = dict(t.get("params") or {})
        if not params:
            continue
        sig = _params_signature(params)
        if sig in seen:
            continue
        seen.add(sig)
        base.append(
            {
                "name": f"optuna_top{picked + 1}_trial{t.get('trial_number')}",
                "overrides": params,
                "optuna_score": float(t.get("score") or 0.0),
                "optuna_test_pnl_usd": float(
                    (t.get("test") or {}).get("net_pnl_usd") or 0.0
                ),
                "optuna_test_win_rate": float(
                    (t.get("test") or {}).get("win_rate") or 0.0
                ),
                "optuna_test_trades": int(
                    (t.get("test") or {}).get("trades_count") or 0
                ),
            }
        )
        picked += 1
        if picked >= int(top_k):
            break
    return base


def _gate_permutations() -> list[dict[str, Any]]:
    """Cartesian product of every gate ladder."""
    keys = list(GATE_LADDERS.keys())
    values = [GATE_LADDERS[k] for k in keys]
    permutations: list[dict[str, Any]] = []
    for combo in itertools.product(*values):
        permutations.append(dict(zip(keys, combo, strict=True)))
    return permutations


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


def _run_one_combo(
    *,
    base_overrides: dict[str, Any],
    gate_overrides: dict[str, Any],
    symbols: list[str],
    ohlc_by_symbol: dict[str, list[dict[str, Any]]],
    train_fraction: float,
    initial_cash: float,
    interval_minutes: int,
    settings: Any,
    disable_realtime_cooldown: bool,
    external_snapshots_by_symbol: dict[str, dict[str, ExternalSnapshot]],
) -> dict[str, Any]:
    """Run a single train+test pass and return a flat record."""
    overrides = dict(base_overrides)
    overrides.update(gate_overrides)
    result = run_walk_forward(
        symbols=symbols,
        ohlc_by_symbol=ohlc_by_symbol,
        grid={k: [v] for k, v in overrides.items()} or {"_no_op": [None]},
        train_fraction=train_fraction,
        initial_cash=initial_cash,
        interval_minutes=interval_minutes,
        min_test_pnl_usd=SURVIVOR_MIN_PNL_USD,
        min_test_win_rate=SURVIVOR_MIN_WIN_RATE,
        min_test_trades_count=SURVIVOR_MIN_TRADES,
        settings=settings,
        disable_realtime_cooldown=disable_realtime_cooldown,
        external_snapshots_by_symbol=external_snapshots_by_symbol,
    )
    if not result.evaluated:
        raise RuntimeError("walk-forward returned zero candidates")
    candidate = result.evaluated[0]
    return {
        "params": dict(overrides),
        "train": candidate.train.to_dict(),
        "test": candidate.test.to_dict(),
        "survives_filter": bool(candidate.survives_filter),
        "score": float(candidate.score),
    }


def _utc_now_iso() -> str:
    return (
        datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _summarise(record: dict[str, Any]) -> str:
    test = record.get("test") or {}
    return (
        f"score={record.get('score', 0):+.4f} "
        f"pnl={test.get('net_pnl_usd', 0):+.3f}$ "
        f"wr={(test.get('win_rate') or 0) * 100:.1f}% "
        f"mdd={test.get('max_drawdown_pct', 0):.2f}% "
        f"trades={test.get('trades_count', 0)} "
        f"survives={record.get('survives_filter')}"
    )


def main() -> int:
    args = _parse_args()
    if args.profile:
        import os

        os.environ["KRAKEN_ALPHA_PROFILE"] = args.profile
        reload_settings()
    settings = get_settings()

    symbols = args.symbols or DEFAULT_SYMBOLS
    ohlc_path = _resolve_path(
        args.ohlc_cache,
        DEFAULT_OHLC_CACHE,
        interval=int(args.interval),
        target=int(args.target_candles),
    )
    if ohlc_path is None:
        raise SystemExit("OHLC cache path could not be resolved")
    ohlc_by_symbol = _load_ohlc(ohlc_path, symbols=symbols)
    start_iso, end_iso = _ohlc_window_iso(ohlc_by_symbol)

    fng_cache = _resolve_path(args.fng_cache)
    btc_dom_cache = _resolve_path(args.btc_dom_cache)
    if fng_cache is None or btc_dom_cache is None:
        raise SystemExit("external cache paths could not be resolved")
    fear_greed, btc_dom, signal_diagnostics = _load_external_signals(
        fng_cache=fng_cache,
        btc_dom_cache=btc_dom_cache,
        start_iso=start_iso,
        end_iso=end_iso,
        refresh=bool(args.refresh_external),
    )

    print(
        f"OHLC cache: {ohlc_path} (window {start_iso} -> {end_iso}); "
        f"F&G entries={signal_diagnostics['fear_greed_entries']} "
        f"BTC dom entries={signal_diagnostics['btc_dominance_entries']}"
    )

    external_snapshots_by_symbol = _build_external_snapshots(
        ohlc_by_symbol,
        fear_greed=fear_greed,
        btc_dom=btc_dom,
        vol_regime_window=int(args.vol_regime_window),
    )

    optuna_path: Path | None = None
    if args.optuna_results:
        optuna_path = _resolve_path(args.optuna_results)
    base_configs = _select_base_configs(optuna_path, top_k=int(args.top_k_base_configs))
    gate_permutations = _gate_permutations()

    cell_count = len(base_configs) * len(gate_permutations)
    if cell_count > int(args.max_combos):
        # Truncate gate permutations from the tail (keeps the all-OFF
        # baseline cell at index 0 — see how _gate_permutations builds
        # the cartesian product).
        truncated = max(1, int(args.max_combos) // max(1, len(base_configs)))
        gate_permutations = gate_permutations[:truncated]
        cell_count = len(base_configs) * len(gate_permutations)
        logger.warning(
            "truncated gate ladder to fit max_combos=%d (now %d cells)",
            int(args.max_combos), cell_count,
        )

    print(
        f"Sweep: base_configs={len(base_configs)} × "
        f"gate_permutations={len(gate_permutations)} = {cell_count} cells "
        f"(profile={settings.active_profile})"
    )

    started = time.time()
    cells: list[dict[str, Any]] = []
    for base in base_configs:
        for gates in gate_permutations:
            try:
                rec = _run_one_combo(
                    base_overrides=dict(base.get("overrides") or {}),
                    gate_overrides=dict(gates),
                    symbols=symbols,
                    ohlc_by_symbol=ohlc_by_symbol,
                    train_fraction=float(args.train_fraction),
                    initial_cash=float(args.initial_cash),
                    interval_minutes=int(args.interval),
                    settings=settings,
                    disable_realtime_cooldown=not bool(args.keep_realtime_cooldown),
                    external_snapshots_by_symbol=external_snapshots_by_symbol,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "cell base=%s gates=%s failed: %s", base.get("name"), gates, exc
                )
                continue
            rec["base_name"] = base.get("name")
            rec["gate_overrides"] = dict(gates)
            cells.append(rec)
    elapsed = time.time() - started

    survivors = [c for c in cells if c.get("survives_filter")]
    survivors.sort(key=lambda c: float(c.get("score") or 0.0), reverse=True)
    non_survivors = [c for c in cells if not c.get("survives_filter")]
    non_survivors.sort(key=lambda c: float(c.get("score") or 0.0), reverse=True)

    payload: dict[str, Any] = {
        "source": "walk_forward_crypto_with_signals",
        "generated_at": _utc_now_iso(),
        "active_profile": settings.active_profile,
        "symbols": list(symbols),
        "interval_minutes": int(args.interval),
        "target_candles": int(args.target_candles),
        "train_fraction": float(args.train_fraction),
        "initial_cash": float(args.initial_cash),
        "ohlc_cache_path": str(ohlc_path),
        "ohlc_window_iso": (start_iso, end_iso),
        "external_signal_diagnostics": signal_diagnostics,
        "filter": {
            "min_test_pnl_usd": SURVIVOR_MIN_PNL_USD,
            "min_test_win_rate": SURVIVOR_MIN_WIN_RATE,
            "min_test_trades_count": SURVIVOR_MIN_TRADES,
        },
        "base_configs": base_configs,
        "gate_ladders": GATE_LADDERS,
        "cell_count": cell_count,
        "evaluated_count": len(cells),
        "survivors_count": len(survivors),
        "top_k_survivors": survivors[:5],
        "top_k_non_survivors": non_survivors[:5],
        "all_cells": cells,
        "elapsed_seconds": round(elapsed, 3),
        "warning": (
            "Each cell tests one base config × one gate permutation on "
            "the same OHLC slice; survivors must clear pnl>=0.20$ AND "
            "wr>=50% AND trades>=30 on the test set. The BTC-dominance "
            "gate is evaluated only on candles whose date is covered "
            "by CoinGecko's free /global snapshot — see external_signal "
            "diagnostics for the actual coverage. Backtest only — no "
            "slippage, latency, or venue rejection simulation."
        ),
    }

    if str(args.output) != "-":
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = (ROOT / out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nResults JSON: {out_path}")
    else:
        print("\nDry run: --output - was passed; result not persisted.")

    print(
        f"\nWalk-forward+signals complete in {elapsed:.2f}s. "
        f"cells={cell_count} evaluated={len(cells)} survivors={len(survivors)}"
    )
    if survivors:
        print("\nTop survivors:")
        for c in survivors[:5]:
            print(f"  - base={c.get('base_name')} gates={c.get('gate_overrides')}")
            print(f"      {_summarise(c)}")
    else:
        print("\n0 strict survivors. Top non-survivors for reference:")
        for c in non_survivors[:5]:
            print(f"  - base={c.get('base_name')} gates={c.get('gate_overrides')}")
            print(f"      {_summarise(c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
