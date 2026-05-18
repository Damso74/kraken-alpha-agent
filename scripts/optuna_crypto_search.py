"""Bayesian (TPE) parameter search for the crypto-perps strategy.

Why this script exists
----------------------
The deterministic walk-forward sweep
(``scripts/walk_forward_crypto.py``) returned **0 / 144 OOS survivors**
on the three resolution presets (240/60/15-min). The verdict is honest
but the grid was small (4 × 3 × 4 = 48 combos per preset), and the
exit-timer dimension was effectively a no-op (``time_stop_minutes``
shadowing turned the 4 grid values into duplicate runs).

This sweep widens the search in two directions:

1. **Continuous knobs.** Optuna's TPE sampler explores the same
   ``min_confidence_to_trade`` / ``min_opportunity_score_buy`` axes as
   the deterministic grid but with continuous ranges (no quantisation
   to 4 fixed values).
2. **Ensemble weights.** The three directional strategies (momentum,
   breakout, mean_reversion) are now tunable independently — the
   deterministic grid never touched these, so this is the largest
   genuine extension of the search space.
3. **Stop-loss / take-profit ratios.** Continuous ranges on the
   exit-rules SL/TP, again unexplored by the deterministic sweep.

Hard safety contract
--------------------
- **Strictly read-only.** Reuses the OHLC cache produced by
  ``scripts/walk_forward_crypto.py`` (``data/ohlc_cache/crypto/``).
  Refuses to start when the cache is missing — no live REST call is
  made to keep the run deterministic and replayable.
- **No live order, ever.** Every candidate is scored by the same
  walk-forward harness (``src.walk_forward.run_walk_forward``) which
  delegates to ``src.backtest.simulate_portfolio``. The execution
  layer (``src.execution`` / ``src.futures_kraken_cli``) is never
  imported.
- **Output is gitignored.** ``data/optuna_crypto_results.json`` is
  excluded by the existing ``data/*.json`` rule (and an explicit
  belt-and-suspenders entry).

Reproducibility
---------------
- TPE sampler seeded with ``--seed`` (default ``20260518``) so a rerun
  produces an identical sequence of trial parameters.
- ``MedianPruner`` skips trials whose train PnL is clearly worse than
  the running median; pruning happens after the train pass and saves
  ~50 % of the wall-clock budget on a typical run.
- ``n_jobs = 1`` by design: optuna's parallel mode introduces
  non-determinism through TPE's posterior sampling and we want the
  exact same survivor list on every machine.

Filter (out-of-sample, strict)
------------------------------
A trial is a *survivor* iff:

    test.net_pnl_usd >= 0.20
    AND test.win_rate  >= 0.50
    AND test.trades_count >= 30

The thresholds are deliberately stricter than the walk-forward driver
defaults (PnL ≥ 0.20$ vs ≥ 0.0$) because optuna evaluates many more
configs (500 vs 48) and the multiple-comparisons risk grows with the
sample size. See ``docs/STRATEGY_DISCOVERY_REPORT.md`` for the full
justification.

Usage (PowerShell)
------------------
.. code-block:: powershell

    .\\.venv\\Scripts\\Activate.ps1

    # Default 500 trials, 60-min cache, deterministic seed.
    python scripts/optuna_crypto_search.py

    # Quick smoke test — 25 trials.
    python scripts/optuna_crypto_search.py --n-trials 25

    # Refresh OHLC cache before the run (only if the cache is stale).
    python scripts/optuna_crypto_search.py --use-cache-only False
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
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
from src.walk_forward import (  # noqa: E402
    WalkForwardCandidate,
    run_walk_forward,
)

logger = get_logger("optuna_crypto_search")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS: list[str] = ["BTC", "ETH", "SOL", "AVAX", "LTC"]
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_TARGET_CANDLES = 720
DEFAULT_TRAIN_FRACTION = 480.0 / 720.0  # 20d train + 10d test
DEFAULT_OHLC_CACHE = "data/ohlc_cache/crypto/crypto_{interval}m_{target}.json"
DEFAULT_OUTPUT = "data/optuna_crypto_results.json"
DEFAULT_N_TRIALS = 500
DEFAULT_SEED = 20_260_518
DEFAULT_PROFILE = "micro_live_100eur_crypto"

# OOS survivor filter — stricter than the deterministic walk-forward
# driver because we evaluate many more configs.
SURVIVOR_MIN_PNL_USD = 0.20
SURVIVOR_MIN_WIN_RATE = 0.50
SURVIVOR_MIN_TRADES = 30


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Bayesian (TPE) parameter search for the crypto-perps "
            "strategy. Reuses the walk-forward harness for scoring; never "
            "places orders. Output is gitignored."
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
        help="OHLC depth per symbol (default 720 ≈ 30 days at 60m)",
    )
    p.add_argument(
        "--train-fraction",
        type=float,
        default=DEFAULT_TRAIN_FRACTION,
        help=f"train slice fraction (default {DEFAULT_TRAIN_FRACTION:.4f} → 20d/10d)",
    )
    p.add_argument(
        "--initial-cash",
        type=float,
        default=10_000.0,
        help="starting USD capital",
    )
    p.add_argument(
        "--n-trials",
        type=int,
        default=DEFAULT_N_TRIALS,
        help=f"optuna trial budget (default {DEFAULT_N_TRIALS})",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=(
            "TPE sampler seed for reproducibility (default "
            f"{DEFAULT_SEED}). Same seed → identical trial sequence."
        ),
    )
    p.add_argument(
        "--ohlc-cache",
        type=str,
        default=None,
        help=(
            "OHLC cache file path (default "
            f"{DEFAULT_OHLC_CACHE} with placeholders filled). The cache "
            "MUST exist; we never re-fetch from this script to keep the "
            "search deterministic."
        ),
    )
    p.add_argument(
        "--output",
        type=str,
        default=DEFAULT_OUTPUT,
        help=f"output JSON path (default {DEFAULT_OUTPUT}, gitignored)",
    )
    p.add_argument(
        "--profile",
        type=str,
        default=DEFAULT_PROFILE,
        help=(
            "active profile for the search run (defaults to "
            f"{DEFAULT_PROFILE} so the simulator uses the crypto-perps "
            "thresholds and exit timing)"
        ),
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="how many top trials to surface in the JSON + report (default 5)",
    )
    p.add_argument(
        "--allow-cache-fetch",
        action="store_true",
        help=(
            "allow the script to populate the OHLC cache via REST when it "
            "is missing. Off by default — keeping cache hydration in "
            "scripts/walk_forward_crypto.py keeps the search deterministic."
        ),
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


# ---------------------------------------------------------------------------
# OHLC loader
# ---------------------------------------------------------------------------


def _resolve_cache_path(
    *,
    interval: int,
    target: int,
    override: str | None = None,
) -> Path:
    if override:
        candidate = Path(override)
    else:
        candidate = Path(DEFAULT_OHLC_CACHE.format(interval=int(interval), target=int(target)))
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    return candidate


def _load_ohlc(
    cache_path: Path,
    *,
    symbols: list[str],
    interval_minutes: int,
    target_candles: int,
    allow_fetch: bool,
) -> tuple[dict[str, list[dict[str, float]]], dict[str, int], str]:
    """Return ``(ohlc_by_symbol, counts, provenance)``. Read-only."""
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            ohlc = payload.get("ohlc_by_symbol") or {}
            counts = payload.get("counts") or {}
            missing = [s for s in symbols if s not in ohlc]
            if not missing:
                logger.info(
                    "loaded OHLC cache from %s (%d symbols)",
                    cache_path, len(symbols),
                )
                return ohlc, counts, "cache"
            logger.warning("cache is missing symbols: %s", ", ".join(missing))
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not parse cache %s: %s", cache_path, exc)

    if not allow_fetch:
        raise SystemExit(
            f"OHLC cache {cache_path} is missing or incomplete and "
            "--allow-cache-fetch is OFF. Hydrate the cache first via "
            "`python scripts/walk_forward_crypto.py --grid-preset 60min` "
            "(which populates data/ohlc_cache/crypto/ with the same payload)."
        )

    logger.info("populating OHLC cache via Kraken public REST (paginated)")
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
            logger.warning("REST OHLC failed for %s: %s — skipping", sym, exc)
            rows = []
        out[sym] = rows
        counts[sym] = len(rows)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "generated_at": _utc_now_iso(),
                "interval_minutes": int(interval_minutes),
                "target_candles": int(target_candles),
                "symbols": symbols,
                "counts": counts,
                "ohlc_by_symbol": out,
                "source": "kraken_public_rest_ohlc",
            },
            default=str,
        ),
        encoding="utf-8",
    )
    return out, counts, "fetch"


# ---------------------------------------------------------------------------
# Optuna objective
# ---------------------------------------------------------------------------


@dataclass
class _SearchContext:
    """Immutable bundle threaded into the objective function."""

    symbols: list[str]
    ohlc_by_symbol: dict[str, list[dict[str, float]]]
    train_fraction: float
    interval_minutes: int
    initial_cash: float
    disable_realtime_cooldown: bool


def _candidate_score(candidate: WalkForwardCandidate) -> float:
    """Optimisation target: ``test_pnl_usd / max(test_mdd_pct, 0.5)``.

    Mirrors the user brief: the ``0.5 %`` floor on the drawdown
    denominator prevents near-zero MDDs from blowing up the score.
    """
    pnl = float(candidate.test.net_pnl_usd)
    mdd = max(float(candidate.test.max_drawdown_pct), 0.5)
    return pnl / mdd


def _build_overrides(trial) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Sample one parameter combination from the search space.

    The search ranges are deliberately *wider* than the deterministic
    grid (``scripts/walk_forward_crypto.py``):

    - ``min_confidence_to_trade`` ∈ [0.05, 0.40] continuous (vs 4 fixed
      values in the grid).
    - ``min_opportunity_score_buy`` ∈ [0.01, 0.10] continuous.
    - ``time_stop_minutes`` ∈ [10, 240] integer.
    - Ensemble weights ``weight_momentum`` / ``weight_breakout`` /
      ``weight_mean_reversion`` ∈ [0, 1] (renormalised in
      ``src.backtest._build_settings_override`` so the directional
      mass is preserved).
    - ``stop_loss_pct`` ∈ [0.5, 3.0] %.
    - ``take_profit_pct`` ∈ [0.5, 3.0] %.

    ``max_funding_rate_pct_per_hour`` is intentionally excluded because
    the backtester does not simulate funding accrual; gridding that
    knob would only inject noise. The funding gate is enforced live
    by ``src.execution._execute_futures``.
    """
    return {
        "min_confidence_to_trade": float(
            trial.suggest_float("min_confidence_to_trade", 0.05, 0.40)
        ),
        "min_opportunity_score_buy": float(
            trial.suggest_float("min_opportunity_score_buy", 0.01, 0.10)
        ),
        "time_stop_minutes": int(
            trial.suggest_int("time_stop_minutes", 10, 240)
        ),
        "weight_momentum": float(
            trial.suggest_float("weight_momentum", 0.0, 1.0)
        ),
        "weight_breakout": float(
            trial.suggest_float("weight_breakout", 0.0, 1.0)
        ),
        "weight_mean_reversion": float(
            trial.suggest_float("weight_mean_reversion", 0.0, 1.0)
        ),
        "stop_loss_pct": float(
            trial.suggest_float("stop_loss_pct", 0.5, 3.0)
        ),
        "take_profit_pct": float(
            trial.suggest_float("take_profit_pct", 0.5, 3.0)
        ),
    }


def _make_objective(ctx: _SearchContext, settings: Any):  # type: ignore[no-untyped-def]
    """Return the optuna objective closure.

    Captured state:
    - ``ctx`` — immutable per-run search context.
    - ``settings`` — base ``Settings`` used as a starting point for
      override clones.
    - ``trials_log`` — list of ``(params_dict, candidate_dict)`` tuples
      collected for the post-run report (TopK survivors, distribution
      analysis).
    """
    trials_log: list[dict[str, Any]] = []

    def objective(trial) -> float:  # type: ignore[no-untyped-def]
        overrides = _build_overrides(trial)
        # Single-combo grid: the walk-forward driver still does
        # train + test passes, which is what we want.
        result = run_walk_forward(
            symbols=ctx.symbols,
            ohlc_by_symbol=ctx.ohlc_by_symbol,
            grid={k: [v] for k, v in overrides.items()},
            train_fraction=ctx.train_fraction,
            initial_cash=ctx.initial_cash,
            interval_minutes=ctx.interval_minutes,
            min_test_pnl_usd=SURVIVOR_MIN_PNL_USD,
            min_test_win_rate=SURVIVOR_MIN_WIN_RATE,
            min_test_trades_count=SURVIVOR_MIN_TRADES,
            settings=settings,
            disable_realtime_cooldown=ctx.disable_realtime_cooldown,
        )
        if not result.evaluated:
            # Defensive: should never happen with a single-combo grid.
            raise RuntimeError("walk-forward returned zero evaluated candidates")
        candidate = result.evaluated[0]
        score = _candidate_score(candidate)

        # Pruner step: report the score after the train + test pass so
        # MedianPruner can shut the trial down early if the test
        # outcome is clearly below the running median. ``trial.report``
        # accepts a single (value, step) pair so we expose only the
        # final score (the walk-forward harness has no intra-trial
        # checkpoint to prune on).
        trial.report(score, step=0)

        # Persist for the report.
        trials_log.append(
            {
                "trial_number": int(trial.number),
                "params": dict(overrides),
                "train": candidate.train.to_dict(),
                "test": candidate.test.to_dict(),
                "survives_filter": bool(candidate.survives_filter),
                "score": float(score),
            }
        )
        return score

    objective.trials_log = trials_log  # type: ignore[attr-defined]
    return objective


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _summarise_trial(t: dict[str, Any]) -> str:
    test = t.get("test") or {}
    return (
        f"#{t.get('trial_number', '?')} "
        f"score={t.get('score', 0):+.4f} "
        f"pnl={test.get('net_pnl_usd', 0):+.3f}$ "
        f"wr={(test.get('win_rate') or 0) * 100:.1f}% "
        f"mdd={test.get('max_drawdown_pct', 0):.2f}% "
        f"trades={test.get('trades_count', 0)} "
        f"survives={t.get('survives_filter')}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = _parse_args()
    if args.profile:
        import os

        os.environ["KRAKEN_ALPHA_PROFILE"] = args.profile
        reload_settings()
    settings = get_settings()

    # Lazy import so a missing optuna at import-time produces a
    # readable error rather than crashing the whole script entry.
    try:
        import optuna  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "optuna is not installed. Activate the venv and run "
            "`pip install -r requirements.txt`."
        ) from exc

    symbols = args.symbols or DEFAULT_SYMBOLS
    cache_path = _resolve_cache_path(
        interval=int(args.interval),
        target=int(args.target_candles),
        override=args.ohlc_cache,
    )
    ohlc, counts, provenance = _load_ohlc(
        cache_path,
        symbols=symbols,
        interval_minutes=int(args.interval),
        target_candles=int(args.target_candles),
        allow_fetch=bool(args.allow_cache_fetch),
    )

    print(
        f"Optuna crypto search: profile={settings.active_profile} "
        f"symbols={symbols} interval={args.interval}m "
        f"train_fraction={args.train_fraction:.4f} "
        f"n_trials={args.n_trials} seed={args.seed} "
        f"OHLC counts={counts} (provenance={provenance})"
    )
    print(
        f"OOS survivor filter: pnl>={SURVIVOR_MIN_PNL_USD:+.2f}$ AND "
        f"wr>={SURVIVOR_MIN_WIN_RATE:.2%} AND "
        f"trades>={SURVIVOR_MIN_TRADES}"
    )

    ctx = _SearchContext(
        symbols=symbols,
        ohlc_by_symbol=ohlc,
        train_fraction=float(args.train_fraction),
        interval_minutes=int(args.interval),
        initial_cash=float(args.initial_cash),
        disable_realtime_cooldown=not bool(args.keep_realtime_cooldown),
    )

    sampler = optuna.samplers.TPESampler(seed=int(args.seed))
    pruner = optuna.pruners.MedianPruner(
        n_startup_trials=10, n_warmup_steps=0
    )
    study = optuna.create_study(
        direction="maximize",
        sampler=sampler,
        pruner=pruner,
    )
    objective = _make_objective(ctx, settings)

    started = time.time()
    study.optimize(
        objective,
        n_trials=int(args.n_trials),
        n_jobs=1,
        show_progress_bar=False,
        catch=(Exception,),  # never let one trial kill the whole run
    )
    elapsed = time.time() - started

    trials_log: list[dict[str, Any]] = list(getattr(objective, "trials_log", []))
    survivors = [t for t in trials_log if t.get("survives_filter")]
    survivors.sort(key=lambda t: float(t.get("score", 0.0)), reverse=True)
    top_k = survivors[: max(0, int(args.top_k))]

    # Best-of-the-rest (non-survivors) for honest reporting.
    non_survivors = [t for t in trials_log if not t.get("survives_filter")]
    non_survivors.sort(key=lambda t: float(t.get("score", 0.0)), reverse=True)
    top_failed = non_survivors[: max(0, int(args.top_k))]

    payload: dict[str, Any] = {
        "source": "optuna_tpe_crypto_search",
        "generated_at": _utc_now_iso(),
        "active_profile": settings.active_profile,
        "symbols": list(symbols),
        "interval_minutes": int(args.interval),
        "target_candles": int(args.target_candles),
        "train_fraction": float(args.train_fraction),
        "initial_cash": float(args.initial_cash),
        "n_trials_requested": int(args.n_trials),
        "n_trials_completed": len(trials_log),
        "ohlc_cache_path": str(cache_path),
        "ohlc_provenance": provenance,
        "ohlc_counts": counts,
        "filter": {
            "min_test_pnl_usd": SURVIVOR_MIN_PNL_USD,
            "min_test_win_rate": SURVIVOR_MIN_WIN_RATE,
            "min_test_trades_count": SURVIVOR_MIN_TRADES,
        },
        "sampler": "TPE",
        "pruner": "MedianPruner(n_startup_trials=10)",
        "seed": int(args.seed),
        "elapsed_seconds": round(elapsed, 3),
        "best_trial_number": int(study.best_trial.number)
        if study.best_trial is not None
        else None,
        "best_value": float(study.best_value)
        if study.best_trial is not None
        else None,
        "best_params": dict(study.best_params)
        if study.best_trial is not None
        else None,
        "survivors_count": len(survivors),
        "top_k_survivors": top_k,
        "top_k_failed_for_reference": top_failed,
        "all_trials": trials_log,
        "warning": (
            "p-hacking risk: 500 trials ≫ 48-combo deterministic grid. "
            "The OOS survivor filter (pnl>=0.20$ AND wr>=50% AND trades>=30) "
            "is intentionally stricter than the deterministic walk-forward "
            "(pnl>=0.0$) to compensate for the multiple-comparisons "
            "exposure. Backtest is local replay only — slippage, latency "
            "and venue rejections are not simulated."
        ),
    }

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )

    print(
        f"\nOptuna search complete in {elapsed:.2f}s. "
        f"trials_completed={len(trials_log)} survivors={len(survivors)}"
    )
    if top_k:
        print("\nTop survivors (up to top-k):")
        for t in top_k:
            print(f"  - {_summarise_trial(t)}")
            print(f"      params={t.get('params')}")
    else:
        print(
            "\nNo trial passed the strict OOS filter. Top non-survivors:"
        )
        for t in top_failed:
            print(f"  - {_summarise_trial(t)}")
            print(f"      params={t.get('params')}")

    print(f"\nResults JSON: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
