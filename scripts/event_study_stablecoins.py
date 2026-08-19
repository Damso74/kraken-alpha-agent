"""Event study: stablecoin supply shocks vs crypto forward returns (Phase 11).

Read-only harness — no trading, no config.yaml changes.

Phase 11 pre-registration runs all four frozen thresholds (7d/30d × high/low)
with shift +30d, random-date, and wrong-direction-lag placebos.

Usage
-----
.. code-block:: powershell

    python scripts/event_study_stablecoins.py --phase11 --days 365 \\
        --ohlc-source binance-public --use-cache-only

    python scripts/event_study_stablecoins.py --use-cache-only \\
        --z-threshold 1.0 --direction high --lag 7
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _event_study_common import (  # noqa: E402
    OHLC_SOURCE_BINANCE,
    REPO_ROOT,
    add_common_event_study_args,
    align_events_to_daily_candles,
    fetch_daily_ohlc,
    fetch_daily_ohlc_from_args,
    window_iso_range,
    write_json_report,
)

from src.crypto_ohlc_rest import CryptoOHLCFetchError
from src.data.collectors._common import CollectorError
from src.data.collectors.defillama import (
    default_defillama_cache_path,
    fetch_stablecoin_supply,
)
from src.research.event_study import EventStudyWindow, run_event_study
from src.research.placebo import (
    benjamini_hochberg,
    empirical_p_value,
    random_events_from_candles,
    shift_events_in_time,
)
from src.signals.stablecoin_supply import (
    StablecoinThresholdSpec,
    build_preregistered_stablecoin_events,
    build_stablecoin_supply_events,
    preregistered_threshold_specs,
)

TAG = "stablecoins"
DEFAULT_CACHE = REPO_ROOT / default_defillama_cache_path()
PHASE11_OUTPUT_DIR = REPO_ROOT / "reports" / "research_runs_phase11"
PHASE11_RUN_LOG = PHASE11_OUTPUT_DIR / "RUN_LOG.md"

# Phase 11 targets: BTC return 3d/7d, ETH if available, realized_vol 7d.
PHASE11_WINDOWS = (
    EventStudyWindow("post_3", 1, 3),
    EventStudyWindow("post_7", 1, 7),
)
PHASE11_METRICS = ("return", "realized_vol")
PHASE11_TICKERS = ("BTC", "ETH")
PHASE11_MIN_EVENTS = 5
SHIFT30_DAYS = 30
PREREGISTRATION_FROZEN_AT = "2026-05-19"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Event study: DefiLlama stablecoin supply z-score vs forward "
            "BTC/ETH returns (read-only). Use --phase11 for frozen thresholds."
        ),
    )
    add_common_event_study_args(p, default_ticker="BTC", default_days=365)
    p.add_argument(
        "--phase11",
        action="store_true",
        help=(
            "Run all four pre-registered thresholds to "
            "reports/research_runs_phase11/ (no grid search)."
        ),
    )
    p.add_argument(
        "--z-threshold",
        type=float,
        default=1.5,
        help="Minimum z-score (single-threshold mode; default 1.5).",
    )
    p.add_argument(
        "--lookback",
        type=int,
        default=180,
        help="Rolling z-score window in days (default 180).",
    )
    p.add_argument(
        "--lag",
        type=int,
        default=7,
        choices=(7, 30),
        help="Supply change horizon in days (default 7).",
    )
    p.add_argument(
        "--direction",
        choices=("high", "low", "abs"),
        default="high",
        help="Event tail: high=expansion, low=contraction (default high).",
    )
    p.add_argument(
        "--cache-path",
        type=Path,
        default=DEFAULT_CACHE,
        help="DefiLlama JSON cache path.",
    )
    return p.parse_args()


def _load_supply_rows(
    start_iso: str,
    end_iso: str,
    cache_path: Path,
    *,
    use_cache_only: bool,
) -> list[dict]:
    if use_cache_only:

        def _blocked() -> dict:
            raise CollectorError("use_cache_only: network fetch disabled")

        rows = fetch_stablecoin_supply(
            start_iso,
            end_iso,
            cache_path=cache_path,
            fetcher=_blocked,  # type: ignore[arg-type]
        )
    else:
        rows = fetch_stablecoin_supply(start_iso, end_iso, cache_path=cache_path)
    return [dict(r) for r in rows]


def compute_phase11_verdict(
    *,
    n_events: int,
    bh_rejected: int,
    placebo_pass: bool,
    min_events: int = PHASE11_MIN_EVENTS,
) -> str:
    """Phase 11 verdict ladder (research-only — not tradable)."""
    if n_events < min_events:
        return "blocked: insufficient events"
    if bh_rejected == 0:
        return "not supported"
    if not placebo_pass:
        return "weak evidence"
    return "candidate for OOS testing (NOT tradable)"


def _placebo_replicate_mean(
    *,
    candles: list[dict[str, Any]],
    events: list[int],
    window: EventStudyWindow,
    metric_name: str,
    sub_seed: int,
) -> float | None:
    if not events:
        return None
    candle_ts = [int(c["timestamp"]) for c in candles]
    placebo_events = random_events_from_candles(
        candle_ts, n_events=len(events), seed=sub_seed
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


def _event_study_mean(
    candles: list[dict[str, Any]],
    events: list[int],
    *,
    metric: str,
    window: EventStudyWindow,
) -> tuple[float | None, int]:
    if not events:
        return None, 0
    result = run_event_study(
        candles,
        events=events,
        windows=[window],
        metrics=[metric],
        compute_baseline=True,
    )
    row = result.row(metric, window.label)
    if row is None or row.n_events == 0:
        return None, 0
    return float(row.mean), int(row.n_events)


def _shift_placebo_survives(
    *,
    candles: list[dict[str, Any]],
    events: list[int],
    delta_seconds: int,
    observed_mean: float,
    metric: str,
    window: EventStudyWindow,
) -> bool:
    """True when shifted events show a similarly extreme mean (placebo fails)."""
    shifted = align_events_to_daily_candles(
        shift_events_in_time(events, delta_seconds=delta_seconds),
        candles,
    )
    shifted_mean, n = _event_study_mean(
        candles, shifted, metric=metric, window=window
    )
    if shifted_mean is None or n == 0:
        return False
    return abs(shifted_mean) >= abs(observed_mean) * 0.5


def _run_placebo_battery(
    *,
    candles: list[dict[str, Any]],
    events: list[int],
    supply_lag: int,
    n_placebos: int,
    seed: int,
    reference_metric: str = "return",
    reference_window: EventStudyWindow | None = None,
) -> dict[str, Any]:
    """Random bootstrap + shift +30d + wrong-direction lag placebos."""
    window = reference_window or EventStudyWindow("post_7", 1, 7)
    observed_mean, n_used = _event_study_mean(
        candles, events, metric=reference_metric, window=window
    )
    out: dict[str, Any] = {
        "reference_metric": reference_metric,
        "reference_window": window.label,
        "observed_mean": observed_mean,
        "n_events_used": n_used,
    }
    if observed_mean is None or n_used == 0:
        out["random_bootstrap"] = {"p_two_sided": None, "n_replicates": 0}
        out["shift_30d"] = {"delta_seconds": SHIFT30_DAYS * 86_400, "survives": None}
        out["wrong_direction_lag"] = {
            "delta_seconds": -supply_lag * 86_400,
            "survives": None,
        }
        out["placebo_pass"] = False
        return out

    placebo_values: list[float] = []
    for i in range(n_placebos):
        val = _placebo_replicate_mean(
            candles=candles,
            events=events,
            window=window,
            metric_name=reference_metric,
            sub_seed=int(seed) + i,
        )
        if val is not None:
            placebo_values.append(val)

    random_p = None
    if placebo_values:
        random_p = empirical_p_value(
            observed=observed_mean, placebo_values=placebo_values
        ).two_sided

    shift30_survives = _shift_placebo_survives(
        candles=candles,
        events=events,
        delta_seconds=SHIFT30_DAYS * 86_400,
        observed_mean=observed_mean,
        metric=reference_metric,
        window=window,
    )
    wrong_lag_survives = _shift_placebo_survives(
        candles=candles,
        events=events,
        delta_seconds=-supply_lag * 86_400,
        observed_mean=observed_mean,
        metric=reference_metric,
        window=window,
    )

    random_pass = random_p is not None and random_p < 0.05
    shift_pass = not shift30_survives
    wrong_lag_pass = not wrong_lag_survives
    placebo_pass = bool(random_pass and shift_pass and wrong_lag_pass)

    out["random_bootstrap"] = {
        "p_two_sided": random_p,
        "n_replicates": len(placebo_values),
        "pass": random_pass,
    }
    out["shift_30d"] = {
        "delta_seconds": SHIFT30_DAYS * 86_400,
        "survives": shift30_survives,
        "pass": shift_pass,
    }
    out["wrong_direction_lag"] = {
        "delta_seconds": -supply_lag * 86_400,
        "survives": wrong_lag_survives,
        "pass": wrong_lag_pass,
    }
    out["placebo_pass"] = placebo_pass
    return out


def _run_cells_for_ticker(
    *,
    candles: list[dict[str, Any]],
    events: list[int],
    n_placebos: int,
    seed: int,
    alpha: float,
) -> tuple[list[dict[str, Any]], int, list[float]]:
    """Run all Phase 11 metric/window cells; return cells, bh_rejected, raw_ps."""
    bh_input: list[tuple[str, str, float, float, int, float]] = []

    for metric_name in PHASE11_METRICS:
        windows = PHASE11_WINDOWS if metric_name == "return" else (
            EventStudyWindow("post_7", 1, 7),
        )
        for window in windows:
            observed_mean, n_used = _event_study_mean(
                candles, events, metric=metric_name, window=window
            )
            if observed_mean is None or n_used == 0:
                continue
            result = run_event_study(
                candles,
                events=events,
                windows=[window],
                metrics=[metric_name],
                compute_baseline=True,
            )
            row = result.row(metric_name, window.label)
            if row is None:
                continue
            placebo_values: list[float] = []
            for i in range(n_placebos):
                val = _placebo_replicate_mean(
                    candles=candles,
                    events=events,
                    window=window,
                    metric_name=metric_name,
                    sub_seed=int(seed) + i + hash((metric_name, window.label)) % 10_000,
                )
                if val is not None:
                    placebo_values.append(val)
            if not placebo_values:
                continue
            p = empirical_p_value(observed=row.mean, placebo_values=placebo_values)
            bh_input.append(
                (
                    metric_name,
                    window.label,
                    float(row.mean),
                    float(result.baseline.get(metric_name, float("nan"))),
                    int(row.n_events),
                    float(p.two_sided),
                )
            )

    raw_ps = [p for *_rest, p in bh_input]
    bh_rejected = 0
    bh_q: list[float] = []
    bh_mask: list[bool] = []
    if bh_input:
        bh = benjamini_hochberg(raw_ps, alpha=alpha)
        bh_rejected = bh.n_rejected
        bh_q = list(bh.q_values)
        bh_mask = list(bh.rejected)

    cells: list[dict[str, Any]] = []
    for idx, (m, w, mean, base, n, p) in enumerate(bh_input):
        cell: dict[str, Any] = {
            "metric": m,
            "window": w,
            "mean": mean,
            "baseline": base,
            "n_events": n,
            "two_sided_p": p,
        }
        if bh_q:
            cell["bh_q"] = bh_q[idx]
            cell["bh_rejected"] = bh_mask[idx]
        cells.append(cell)

    return cells, bh_rejected, raw_ps


def _run_threshold_study(
    *,
    spec: StablecoinThresholdSpec,
    supply_rows: list[dict],
    ohlc_by_ticker: dict[str, list[dict[str, Any]]],
    lookback: int,
    n_placebos: int,
    seed: int,
    alpha: float,
    window_days: int,
) -> dict[str, Any]:
    raw_events = build_preregistered_stablecoin_events(
        supply_rows, spec, lookback=lookback
    )
    hypothesis = (
        f"{spec.metric} z "
        f"{'>=' if spec.direction == 'high' else '<='} "
        f"{'+' if spec.direction == 'high' else '-'}{spec.z_threshold} "
        f"-> forward return 3d/7d + realized_vol 7d"
    )

    ticker_reports: dict[str, Any] = {}
    aggregate_bh = 0
    any_placebo_pass = False
    primary_candles = ohlc_by_ticker.get("BTC") or next(iter(ohlc_by_ticker.values()))

    aligned_primary = align_events_to_daily_candles(raw_events, primary_candles)
    aggregate_events = len(aligned_primary)
    placebo_battery = _run_placebo_battery(
        candles=primary_candles,
        events=aligned_primary,
        supply_lag=spec.supply_lag,
        n_placebos=n_placebos,
        seed=seed,
    )
    any_placebo_pass = bool(placebo_battery.get("placebo_pass"))

    for ticker, candles in ohlc_by_ticker.items():
        aligned = align_events_to_daily_candles(raw_events, candles)
        cells, bh_rejected, _raw_ps = _run_cells_for_ticker(
            candles=candles,
            events=aligned,
            n_placebos=n_placebos,
            seed=seed + hash(ticker) % 1000,
            alpha=alpha,
        )
        aggregate_bh = max(aggregate_bh, bh_rejected)
        ticker_reports[ticker] = {
            "events_aligned": len(aligned),
            "candles_count": len(candles),
            "cells": cells,
            "bh_rejected": bh_rejected,
        }

    verdict = compute_phase11_verdict(
        n_events=aggregate_events,
        bh_rejected=aggregate_bh,
        placebo_pass=any_placebo_pass,
    )

    return {
        "phase": "11",
        "preregistration_id": spec.preregistration_id,
        "preregistration_frozen_at": PREREGISTRATION_FROZEN_AT,
        "pre_registered_threshold": {
            "metric": spec.metric,
            "supply_lag_days": spec.supply_lag,
            "z_threshold": spec.z_threshold,
            "direction": spec.direction,
            "lookback": lookback,
            "note": "Frozen before run — no grid search.",
        },
        "hypothesis": hypothesis,
        "verdict": verdict,
        "events_count_raw": aggregate_events,
        "events_count_aligned_btc": len(aligned_primary),
        "supply_rows": len(supply_rows),
        "window_days": window_days,
        "n_placebos": n_placebos,
        "seed": seed,
        "alpha": alpha,
        "targets": {
            "return_windows": ["post_3", "post_7"],
            "realized_vol_window": "post_7",
            "tickers": list(ohlc_by_ticker.keys()),
        },
        "placebos": placebo_battery,
        "tickers": ticker_reports,
        "disclaimer": "Research artifact only — not tradable, no profitability claim.",
    }


def _fetch_ohlc_for_tickers(
    args: argparse.Namespace,
    tickers: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for ticker in tickers:
        try:
            candles = fetch_daily_ohlc(
                ticker,
                args.days,
                ohlc_source=getattr(args, "ohlc_source", OHLC_SOURCE_BINANCE),
                ohlc_cache_path=getattr(args, "ohlc_cache_path", None),
                use_cache_only=bool(getattr(args, "use_cache_only", False)),
            )
        except (CryptoOHLCFetchError, CollectorError) as exc:
            print(f"[{TAG}] WARNING {ticker} OHLC skipped: {exc}", file=sys.stderr)
            continue
        if candles:
            out[ticker] = candles
            print(f"[{TAG}] {ticker} daily OHLC: {len(candles)} candles")
    return out


def _append_run_log(entries: list[dict[str, Any]]) -> None:
    PHASE11_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"\n## Run {ts}\n",
        "| preregistration_id | metric | direction | events | BH rej | verdict |",
        "|--------------------|--------|-----------|--------|--------|---------|",
    ]
    for entry in entries:
        spec = entry["pre_registered_threshold"]
        bh = max(
            (t.get("bh_rejected", 0) for t in entry.get("tickers", {}).values()),
            default=0,
        )
        lines.append(
            f"| {entry['preregistration_id']} | {spec['metric']} | "
            f"{spec['direction']} | {entry['events_count_raw']} | {bh} | "
            f"{entry['verdict']} |"
        )
    lines.append("")
    lines.append(
        "> No profitability claim. `candidate for OOS testing` ≠ tradable.\n"
    )
    mode = "a" if PHASE11_RUN_LOG.exists() else "w"
    header = ""
    if mode == "w":
        header = (
            "# Phase 11 — Stablecoin supply pre-registered runs\n\n"
            "Frozen thresholds only (z=±1.0, 7d/30d). "
            "OHLC via `--ohlc-source binance-public`.\n"
        )
    with PHASE11_RUN_LOG.open(mode, encoding="utf-8") as fh:
        if header:
            fh.write(header)
        fh.write("\n".join(lines))


def run_phase11(args: argparse.Namespace) -> int:
    start_iso, end_iso, _ = window_iso_range(args.days)
    try:
        supply_rows = _load_supply_rows(
            start_iso,
            end_iso,
            args.cache_path,
            use_cache_only=args.use_cache_only,
        )
    except (CollectorError, ValueError) as exc:
        print(f"[{TAG}] FATAL supply fetch failed: {exc}", file=sys.stderr)
        return 2
    print(f"[{TAG}] stablecoin supply rows: {len(supply_rows)}")

    ohlc_by_ticker = _fetch_ohlc_for_tickers(args, PHASE11_TICKERS)
    if not ohlc_by_ticker:
        print(f"[{TAG}] FATAL 0 OHLC candles for any ticker", file=sys.stderr)
        return 3

    PHASE11_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_entries: list[dict[str, Any]] = []

    for spec in preregistered_threshold_specs():
        print(f"\n[{TAG}] === {spec.preregistration_id} ===")
        report = _run_threshold_study(
            spec=spec,
            supply_rows=supply_rows,
            ohlc_by_ticker=ohlc_by_ticker,
            lookback=args.lookback,
            n_placebos=args.n_placebos,
            seed=args.seed,
            alpha=args.alpha,
            window_days=args.days,
        )
        print(f"[{TAG}] VERDICT: {report['verdict']}")
        out_path = PHASE11_OUTPUT_DIR / f"{spec.preregistration_id.lower()}.json"
        write_json_report(out_path, report, tag=TAG)
        run_entries.append(report)

    _append_run_log(run_entries)
    print(f"\n[{TAG}] Phase 11 complete — {len(run_entries)} artifacts in {PHASE11_OUTPUT_DIR}")
    return 0


def main() -> int:
    args = parse_args()
    if args.phase11:
        if args.ohlc_source != OHLC_SOURCE_BINANCE:
            print(
                f"[{TAG}] NOTE: Phase 11 recommends --ohlc-source binance-public "
                f"(current: {args.ohlc_source})",
                file=sys.stderr,
            )
        return run_phase11(args)

    start_iso, end_iso, _ = window_iso_range(args.days)
    metric = f"supply_change_{args.lag}d"
    hypothesis = (
        f"{metric} {args.direction} z>={args.z_threshold} -> "
        f"forward {args.ticker} return/vol"
    )

    try:
        supply_rows = _load_supply_rows(
            start_iso,
            end_iso,
            args.cache_path,
            use_cache_only=args.use_cache_only,
        )
    except (CollectorError, ValueError) as exc:
        print(f"[{TAG}] FATAL supply fetch failed: {exc}", file=sys.stderr)
        return 2
    print(f"[{TAG}] stablecoin supply rows: {len(supply_rows)}")

    try:
        candles = fetch_daily_ohlc_from_args(args)
    except CryptoOHLCFetchError as exc:
        print(f"[{TAG}] FATAL OHLC failed: {exc}", file=sys.stderr)
        return 3
    if not candles:
        print(f"[{TAG}] FATAL 0 candles", file=sys.stderr)
        return 3
    print(f"[{TAG}] {args.ticker} daily OHLC: {len(candles)} candles")

    raw_events = build_stablecoin_supply_events(
        supply_rows,
        z_threshold=args.z_threshold,
        lookback=args.lookback,
        lag=args.lag,
        direction=args.direction,
    )
    events = align_events_to_daily_candles(raw_events, candles)

    from _event_study_common import run_event_study_pipeline  # noqa: E402

    code, report = run_event_study_pipeline(
        tag=TAG,
        hypothesis=hypothesis,
        candles=candles,
        events=events,
        n_placebos=args.n_placebos,
        seed=args.seed,
        alpha=args.alpha,
    )
    report["supply_rows"] = len(supply_rows)
    report["z_threshold"] = args.z_threshold
    report["lookback"] = args.lookback
    report["lag"] = args.lag
    report["direction"] = args.direction
    report["ticker"] = args.ticker
    report["window_days"] = args.days

    if args.output_json:
        write_json_report(args.output_json, report, tag=TAG)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
