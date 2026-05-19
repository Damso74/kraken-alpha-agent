"""Event study: daily volume-shock variants vs forward BTC returns (Phase 11).

Read-only harness — no trading, no config.yaml changes.

Pre-registered variants (see :mod:`src.signals.volume_shock`):
``vol_z20_high``, ``vol_z60_high``, ``vol_z20_range_compression``,
``vol_z20_low_abs_return``.

Placebos per variant: random dates (bootstrap), shift +30d, shuffle labels.

Usage
-----
.. code-block:: powershell

    python scripts/event_study_volume_shock.py --days 365 --ohlc-source binance-public
    python scripts/event_study_volume_shock.py --variant vol_z20_high --output-json reports/research_runs_phase11/vol_z20_365d.json
"""

from __future__ import annotations

import argparse
import bisect
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _event_study_common import (  # noqa: E402
    DEFAULT_WINDOWS,
    add_common_event_study_args,
    align_events_to_daily_candles,
    fetch_daily_ohlc_from_args,
    run_event_study_pipeline,
    write_json_report,
)
from src.crypto_ohlc_rest import CryptoOHLCFetchError
from src.research.event_study import EventStudyWindow, run_event_study
from src.research.placebo import empirical_p_value, shift_events_in_time, shuffle_labels
from src.signals.volume_shock import (
    EVENT_VARIANTS,
    EVENT_VARIANT_VOL_Z20,
    build_volume_shock_events,
    event_rate_fraction,
    is_blocked_by_event_rate,
)

TAG = "volume_shock"
SHIFT_DELTA_SECONDS = 86_400 * 30
PHASE11_METRICS = ("return", "realized_vol", "max_drawdown")
# Placebos align to BH-primary window (post_7 per red team Phase 11/12).
PRIMARY_WINDOW = EventStudyWindow("post_7", 1, 7)
BH_REFERENCE_METRIC = "return"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Event study: pre-registered daily volume-shock events vs "
            "forward returns / vol / drawdown (read-only, Phase 11)."
        ),
    )
    add_common_event_study_args(p, default_ticker="BTC", default_days=365)
    p.add_argument(
        "--variant",
        choices=EVENT_VARIANTS,
        default=EVENT_VARIANT_VOL_Z20,
        help=f"Pre-registered event variant (default {EVENT_VARIANT_VOL_Z20!r}).",
    )
    p.add_argument(
        "--run-all-variants",
        action="store_true",
        help="Run every pre-registered variant and write a combined JSON report.",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=_REPO_ROOT / "reports" / "research_runs_phase11",
        help="Directory for JSON artifacts (default reports/research_runs_phase11/).",
    )
    return p.parse_args()


def _per_event_metric_values(
    candles: list[dict[str, Any]],
    events: list[int],
    *,
    metric_name: str,
    window: EventStudyWindow,
) -> list[float]:
    """Collect one metric value per aligned event (for shuffle-label placebo)."""
    from src.research.event_study import METRIC_REGISTRY

    fn = METRIC_REGISTRY[metric_name]
    timestamps = [int(c["timestamp"]) for c in candles]
    values: list[float] = []
    for ev in events:
        idx = bisect.bisect_left(timestamps, int(ev))
        if idx >= len(candles):
            continue
        start = idx + window.start_offset
        end = idx + window.end_offset
        if start < 0 or end >= len(candles):
            continue
        val = fn(candles[start : end + 1], [])
        if val is not None:
            values.append(float(val))
    return values


def _placebo_shift_p_value(
    candles: list[dict[str, Any]],
    events: list[int],
    *,
    observed_mean: float,
    metric_name: str,
    window: EventStudyWindow,
) -> float | None:
    shifted = shift_events_in_time(events, delta_seconds=SHIFT_DELTA_SECONDS)
    aligned = align_events_to_daily_candles(shifted, candles)
    if not aligned:
        return None
    result = run_event_study(
        candles,
        events=aligned,
        windows=[window],
        metrics=[metric_name],
        compute_baseline=False,
    )
    row = result.row(metric_name, window.label)
    if row is None or row.n_events == 0:
        return None
    return empirical_p_value(observed=observed_mean, placebo_values=[row.mean]).two_sided


def _placebo_shuffle_p_value(
    candles: list[dict[str, Any]],
    events: list[int],
    *,
    observed_mean: float,
    metric_name: str,
    window: EventStudyWindow,
    n_placebos: int,
    seed: int,
) -> float | None:
    per_event = _per_event_metric_values(
        candles, events, metric_name=metric_name, window=window
    )
    if len(per_event) < 2:
        return None
    placebo_means: list[float] = []
    for i in range(n_placebos):
        shuffled = shuffle_labels(per_event, seed=int(seed) + 10_000 + i)
        placebo_means.append(sum(shuffled) / len(shuffled))
    return empirical_p_value(observed=observed_mean, placebo_values=placebo_means).two_sided


def compute_research_verdict(
    *,
    n_events: int,
    n_candles: int,
    script_verdict: str,
    bh_rejected: int,
    shift_p: float | None,
    shuffle_p: float | None,
    best_raw_p: float | None,
) -> str:
    """Phase 11 verdict — never ``tradable``."""
    if n_events == 0:
        return "blocked"
    if is_blocked_by_event_rate(n_events, n_candles):
        return "blocked"
    if n_events < 5:
        return "weak evidence"
    if bh_rejected >= 1 and (shift_p is None or shift_p < 0.05) and (
        shuffle_p is None or shuffle_p < 0.05
    ):
        return "candidate for OOS"
    if bh_rejected >= 1:
        return "weak evidence"
    if best_raw_p is not None and best_raw_p < 0.05:
        return "weak evidence"
    if "not supported" in script_verdict:
        return "kill"
    return "kill"


def run_variant_study(
    *,
    variant: str,
    candles: list[dict[str, Any]],
    ticker: str,
    days: int,
    n_placebos: int,
    seed: int,
    alpha: float,
) -> dict[str, Any]:
    hypothesis = (
        f"{variant} on {ticker} daily OHLC -> forward return / vol / max DD "
        f"(z>=2.0 pre-registered; NOT tradeable)"
    )
    raw_events = build_volume_shock_events(candles, variant=variant)
    events = align_events_to_daily_candles(raw_events, candles)
    rate = event_rate_fraction(len(events), len(candles))

    _code, report = run_event_study_pipeline(
        tag=f"{TAG}/{variant}",
        hypothesis=hypothesis,
        candles=candles,
        events=events,
        n_placebos=n_placebos,
        seed=seed,
        alpha=alpha,
        metrics=PHASE11_METRICS,
        windows=DEFAULT_WINDOWS,
    )

    primary_row = None
    rejected_mask = report.get("bh_rejected_mask") or []
    cells = report.get("cells") or []
    for idx, cell in enumerate(cells):
        is_bh = (
            bool(rejected_mask[idx])
            if idx < len(rejected_mask)
            else False
        )
        if is_bh and cell.get("metric") == BH_REFERENCE_METRIC:
            primary_row = cell
            break
    if primary_row is None:
        for cell in cells:
            if (
                cell.get("metric") == BH_REFERENCE_METRIC
                and cell.get("window") == PRIMARY_WINDOW.label
            ):
                primary_row = cell
                break

    shift_p = shuffle_p = None
    placebo_window = PRIMARY_WINDOW
    placebo_metric = BH_REFERENCE_METRIC
    if primary_row:
        placebo_metric = str(primary_row.get("metric", BH_REFERENCE_METRIC))
        wlabel = str(primary_row.get("window", PRIMARY_WINDOW.label))
        for w in DEFAULT_WINDOWS:
            if w.label == wlabel:
                placebo_window = w
                break

    if primary_row and events:
        obs_mean = float(primary_row["mean"])
        shift_p = _placebo_shift_p_value(
            candles,
            events,
            observed_mean=obs_mean,
            metric_name=placebo_metric,
            window=placebo_window,
        )
        shuffle_p = _placebo_shuffle_p_value(
            candles,
            events,
            observed_mean=obs_mean,
            metric_name=placebo_metric,
            window=placebo_window,
            n_placebos=n_placebos,
            seed=seed,
        )

    raw_ps = [float(c["two_sided_p"]) for c in report.get("cells", [])]
    best_raw_p = min(raw_ps) if raw_ps else None
    bh_rejected = int(report.get("bh_rejected", 0))

    research_verdict = compute_research_verdict(
        n_events=len(events),
        n_candles=len(candles),
        script_verdict=str(report.get("verdict", "")),
        bh_rejected=bh_rejected,
        shift_p=shift_p,
        shuffle_p=shuffle_p,
        best_raw_p=best_raw_p,
    )

    report["variant"] = variant
    report["ticker"] = ticker
    report["window_days"] = days
    report["event_rate_fraction"] = round(rate, 4)
    report["g2_blocked_by_rate"] = is_blocked_by_event_rate(len(events), len(candles))
    report["placebos"] = {
        "random_dates_bootstrap_n": n_placebos,
        "shift_plus_30d_seconds": SHIFT_DELTA_SECONDS,
        "aligned_metric": placebo_metric,
        "aligned_window": placebo_window.label,
        "shift_return_post_7_p": shift_p,
        "shuffle_labels_return_post_7_p": shuffle_p,
        "shift_return_post_3_p": shift_p,
        "shuffle_labels_return_post_3_p": shuffle_p,
    }
    report["research_verdict"] = research_verdict
    report["tradable"] = False
    return report


def main() -> int:
    args = parse_args()

    try:
        candles = fetch_daily_ohlc_from_args(args)
    except CryptoOHLCFetchError as exc:
        print(f"[{TAG}] FATAL OHLC failed: {exc}", file=sys.stderr)
        return 3
    if not candles:
        print(f"[{TAG}] FATAL 0 candles", file=sys.stderr)
        return 3
    print(f"[{TAG}] {args.ticker} daily OHLC: {len(candles)} candles")

    variants = list(EVENT_VARIANTS) if args.run_all_variants else [args.variant]
    reports: dict[str, Any] = {
        "tag": TAG,
        "ticker": args.ticker,
        "window_days": args.days,
        "ohlc_source": args.ohlc_source,
        "candles_count": len(candles),
        "variants": {},
    }

    worst_code = 0
    for variant in variants:
        report = run_variant_study(
            variant=variant,
            candles=candles,
            ticker=args.ticker,
            days=args.days,
            n_placebos=args.n_placebos,
            seed=args.seed,
            alpha=args.alpha,
        )
        reports["variants"][variant] = report
        print(
            f"[{TAG}] {variant}: events={report['events_count']} "
            f"rate={report['event_rate_fraction']:.1%} "
            f"research_verdict={report['research_verdict']}"
        )
        rv = report["research_verdict"]
        if rv == "blocked":
            worst_code = max(worst_code, 2)

    if args.output_json is not None:
        out_path = args.output_json
    elif args.run_all_variants:
        out_path = args.output_dir / f"volume_shock_all_{args.days}d.json"
    else:
        out_path = args.output_dir / f"{args.variant}_{args.days}d.json"

    payload = reports if args.run_all_variants else reports["variants"][variants[0]]
    write_json_report(out_path, payload, tag=TAG)

    return worst_code


if __name__ == "__main__":
    raise SystemExit(main())
