"""End-to-end demo for the research harness.

What this script does
---------------------
1. Pulls the Fear & Greed index for the last ``--days`` days through
   :func:`src.external_signals.fetch_fear_greed` (cache-friendly).
2. Pulls BTC daily OHLC from Kraken's public REST endpoint through
   :func:`src.crypto_ohlc_rest.fetch_crypto_ohlc_paginated`. Both
   feeds are read-only and require no Kraken API key.
3. Defines events as the days where Fear & Greed is **below**
   ``--fear-threshold`` (default 25 → "extreme fear" contrarian).
4. Runs an event study over post-event windows
   ``post_1`` / ``post_3`` / ``post_7`` days with metrics
   ``return`` and ``realized_vol``.
5. Runs a placebo bootstrap (``--n-placebos`` replicates,
   default 200): each replicate draws the same number of events
   uniformly at random from the candle index and re-runs the event
   study; the resulting metric distribution is the null.
6. Reports empirical two-sided p-values for each (metric, window)
   cell + a Benjamini–Hochberg FDR correction across all six cells.

This is intentionally a *small* demo with a deliberately weak
hypothesis ("extreme fear precedes a positive 7d return"). It is
expected to fail the BH cut at any honest FDR level on a 180-day
window of BTC — the point is to demonstrate the harness end-to-end
and surface what "rejecting a hypothesis" looks like in practice.

Hard safety contract
--------------------
- Strictly read-only. The script never imports
  :mod:`src.execution`, :mod:`src.futures_kraken_cli` or any module
  that can mutate venue state.
- No Kraken authentication required. The two endpoints (F&G,
  Kraken public REST OHLC) are public.
- Deterministic. The placebo bootstrap uses the seed passed in
  ``--seed``; same seed → same output.

Usage (PowerShell)
------------------
.. code-block:: powershell

    .\\.venv\\Scripts\\Activate.ps1
    python scripts/demo_event_study.py
    python scripts/demo_event_study.py --days 90 --fear-threshold 30
    python scripts/demo_event_study.py --use-cache-only --json-out demo.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.crypto_ohlc_rest import (
    CryptoOHLCFetchError,
    fetch_crypto_ohlc_paginated,
    normalize_crypto_pair,
)
from src.external_signals import (
    ExternalSignalError,
    fetch_fear_greed,
    pick_for_date,
)
from src.research.event_study import (
    EventStudyWindow,
    run_event_study,
)
from src.research.placebo import (
    benjamini_hochberg,
    empirical_p_value,
    random_events_from_candles,
)

DEFAULT_DAYS = 180
DEFAULT_FEAR_THRESHOLD = 25
DEFAULT_N_PLACEBOS = 200
DEFAULT_SEED = 20260519
DEFAULT_TICKER = "BTC"
DEFAULT_CACHE_PATH = REPO_ROOT / "data" / "external_cache" / "fear_greed.json"
SECONDS_PER_DAY = 86_400


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Demo end-to-end run of the research harness on the "
            "'extreme fear precedes a positive 7d return' hypothesis."
        ),
    )
    p.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Look-back window in days (default {DEFAULT_DAYS}).",
    )
    p.add_argument(
        "--ticker",
        type=str,
        default=DEFAULT_TICKER,
        help=f"Crypto ticker to study (default {DEFAULT_TICKER!r}).",
    )
    p.add_argument(
        "--fear-threshold",
        type=int,
        default=DEFAULT_FEAR_THRESHOLD,
        help=(
            "Fear & Greed value strictly below which we declare an "
            f"event (default {DEFAULT_FEAR_THRESHOLD})."
        ),
    )
    p.add_argument(
        "--n-placebos",
        type=int,
        default=DEFAULT_N_PLACEBOS,
        help=(
            "Number of placebo bootstrap replicates "
            f"(default {DEFAULT_N_PLACEBOS})."
        ),
    )
    p.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Master seed for the placebo bootstrap (default {DEFAULT_SEED}).",
    )
    p.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        help="Target FDR for the BH correction (default 0.05).",
    )
    p.add_argument(
        "--cache-path",
        type=Path,
        default=DEFAULT_CACHE_PATH,
        help=(
            "Path to the Fear & Greed cache JSON. Created on first "
            f"run (default {DEFAULT_CACHE_PATH.relative_to(REPO_ROOT)})."
        ),
    )
    p.add_argument(
        "--use-cache-only",
        action="store_true",
        help=(
            "Do not perform live HTTP calls for the Fear & Greed feed. "
            "Fails fast if the cache is empty / missing dates."
        ),
    )
    p.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path; if set, the full report is also written here.",
    )
    return p.parse_args()


def _fetch_fear_greed(
    start_iso: str,
    end_iso: str,
    cache_path: Path,
    *,
    use_cache_only: bool,
) -> dict[date, int]:
    """Wrapper that translates ``use_cache_only`` into a no-network fetcher."""
    if use_cache_only:
        def _empty_fetcher(_limit: int) -> dict:
            raise ExternalSignalError(
                "use_cache_only is set and the cache does not cover the window"
            )

        return fetch_fear_greed(
            start_iso=start_iso,
            end_iso=end_iso,
            cache_path=cache_path,
            fetcher=_empty_fetcher,
        )
    return fetch_fear_greed(
        start_iso=start_iso, end_iso=end_iso, cache_path=cache_path
    )


def _fetch_btc_daily(ticker: str, days: int) -> list[dict[str, Any]]:
    """Pull daily OHLC for the requested ticker via Kraken public REST."""
    pair = normalize_crypto_pair(ticker)
    since = int((datetime.now(timezone.utc) - timedelta(days=days + 5)).timestamp())
    rows = fetch_crypto_ohlc_paginated(
        pair,
        interval_min=1440,
        target_candles=max(days + 10, 30),
        since=since,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "timestamp": int(r.timestamp),
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "vwap": float(r.vwap),
                "volume": float(r.volume),
            }
        )
    return out


def _events_from_fear_greed(
    fg: dict[date, int],
    candles: list[dict[str, Any]],
    threshold: int,
) -> list[int]:
    """Pick candle timestamps whose F&G value is strictly below ``threshold``."""
    events: list[int] = []
    for c in candles:
        d = datetime.fromtimestamp(int(c["timestamp"]), tz=timezone.utc).date()
        val = pick_for_date(fg, d, fallback=None)
        if val is None:
            continue
        try:
            if int(val) < threshold:
                events.append(int(c["timestamp"]))
        except (TypeError, ValueError):
            continue
    return events


def _placebo_replicate_metric(
    *,
    candles: list[dict[str, Any]],
    n_events: int,
    window: EventStudyWindow,
    metric_name: str,
    sub_seed: int,
) -> float | None:
    """One placebo replicate: random events, same window, same metric."""
    if n_events == 0:
        return None
    candle_ts = [int(c["timestamp"]) for c in candles]
    placebo_events = random_events_from_candles(
        candle_ts, n_events=n_events, seed=sub_seed
    )
    result = run_event_study(
        candles,
        events=placebo_events,
        windows=[window],
        metrics=[metric_name],
        compute_baseline=False,
    )
    row = result.row(metric_name, window.label)
    if row is None or row.n_events == 0:
        return None
    return float(row.mean)


def main() -> int:
    args = parse_args()
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=args.days)
    print(
        f"[demo] hypothesis: {args.ticker} daily 'F&G < {args.fear_threshold} → "
        f"positive forward return' on {start} → {today} ({args.days} days)"
    )

    try:
        fg = _fetch_fear_greed(
            start_iso=start.isoformat(),
            end_iso=today.isoformat(),
            cache_path=args.cache_path,
            use_cache_only=args.use_cache_only,
        )
    except ExternalSignalError as exc:
        print(f"[demo] FATAL fear & greed fetch failed: {exc}", file=sys.stderr)
        return 2
    print(f"[demo] Fear & Greed: {len(fg)} daily entries in window")

    try:
        candles = _fetch_btc_daily(args.ticker, args.days)
    except CryptoOHLCFetchError as exc:
        print(f"[demo] FATAL Kraken OHLC fetch failed: {exc}", file=sys.stderr)
        return 3
    if not candles:
        print("[demo] FATAL Kraken returned 0 candles", file=sys.stderr)
        return 3
    print(
        f"[demo] {args.ticker} daily OHLC: {len(candles)} candles "
        f"({datetime.fromtimestamp(candles[0]['timestamp'], tz=timezone.utc).date()} → "
        f"{datetime.fromtimestamp(candles[-1]['timestamp'], tz=timezone.utc).date()})"
    )

    events = _events_from_fear_greed(fg, candles, args.fear_threshold)
    print(
        f"[demo] events where F&G < {args.fear_threshold}: {len(events)} "
        f"({len(events) / max(len(candles), 1):.1%} of candles)"
    )

    if len(events) < 5:
        print(
            "[demo] WARNING fewer than 5 events — statistical power is "
            "negligible. Consider widening --days or relaxing "
            "--fear-threshold."
        )

    windows = (
        EventStudyWindow("post_1", 1, 1),
        EventStudyWindow("post_3", 1, 3),
        EventStudyWindow("post_7", 1, 7),
    )
    metrics = ("return", "realized_vol")
    result = run_event_study(
        candles,
        events=events,
        windows=windows,
        metrics=metrics,
        compute_baseline=True,
    )
    print(
        f"[demo] event study: {result.events_used} used, "
        f"{result.events_skipped_oob} skipped at boundary"
    )

    bh_input: list[tuple[str, str, float, float, int, float]] = []
    print()
    print(
        f"{'metric':<14} {'window':<10} {'n':>4} {'mean':>10} {'baseline':>10} "
        f"{'two-sided p':>14}"
    )
    print("-" * 70)

    for metric_name in metrics:
        for window in windows:
            row = result.row(metric_name, window.label)
            if row is None or row.n_events == 0:
                print(
                    f"{metric_name:<14} {window.label:<10} {0:>4} {'n/a':>10} "
                    f"{'n/a':>10} {'n/a':>14}"
                )
                continue
            placebo_values: list[float] = []
            for i in range(args.n_placebos):
                sub_seed = int(args.seed) + i
                val = _placebo_replicate_metric(
                    candles=candles,
                    n_events=row.n_events,
                    window=window,
                    metric_name=metric_name,
                    sub_seed=sub_seed,
                )
                if val is not None:
                    placebo_values.append(val)
            if not placebo_values:
                print(
                    f"{metric_name:<14} {window.label:<10} {row.n_events:>4} "
                    f"{row.mean:>+10.4f} "
                    f"{result.baseline.get(metric_name, float('nan')):>+10.4f} "
                    f"{'n/a (no placebo)':>14}"
                )
                continue
            p = empirical_p_value(observed=row.mean, placebo_values=placebo_values)
            bh_input.append(
                (
                    metric_name,
                    window.label,
                    row.mean,
                    result.baseline.get(metric_name, float("nan")),
                    row.n_events,
                    p.two_sided,
                )
            )
            print(
                f"{metric_name:<14} {window.label:<10} {row.n_events:>4} "
                f"{row.mean:>+10.4f} "
                f"{result.baseline.get(metric_name, float('nan')):>+10.4f} "
                f"{p.two_sided:>14.4f}"
            )

    if bh_input:
        p_values = [p for *_rest, p in bh_input]
        bh = benjamini_hochberg(p_values, alpha=args.alpha)
        print()
        print(
            f"[demo] Benjamini-Hochberg correction at FDR={args.alpha}: "
            f"{bh.n_rejected}/{len(p_values)} cells reject H0"
        )
        if bh.n_rejected == 0:
            print(
                "[demo] VERDICT: no cell survives the FDR floor. The "
                "hypothesis 'extreme fear → positive forward return' is "
                "not supported on this window of BTC. Move on."
            )
        else:
            print(
                f"[demo] VERDICT: {bh.n_rejected} cell(s) survive the FDR "
                "floor. Re-run on a different asset (ETH, SOL) and a "
                "different window before celebrating."
            )

    if args.json_out:
        report = {
            "hypothesis": (
                f"F&G < {args.fear_threshold} → positive forward return on "
                f"{args.ticker}"
            ),
            "window_days": args.days,
            "fear_threshold": args.fear_threshold,
            "n_placebos": args.n_placebos,
            "seed": args.seed,
            "alpha": args.alpha,
            "candles_count": len(candles),
            "events_count": len(events),
            "events_used": result.events_used,
            "events_skipped_oob": result.events_skipped_oob,
            "baseline": dict(result.baseline),
            "cells": [
                {
                    "metric": m,
                    "window": w,
                    "mean": mean,
                    "baseline": base,
                    "n_events": n,
                    "two_sided_p": p,
                }
                for (m, w, mean, base, n, p) in bh_input
            ],
        }
        if bh_input:
            report["bh_rejected"] = bh.n_rejected
            report["bh_q_values"] = list(bh.q_values)
            report["bh_rejected_mask"] = list(bh.rejected)
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        print(f"[demo] full report written to {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
