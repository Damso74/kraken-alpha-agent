"""Event study: calendar/session boundary events vs crypto forward returns.

Calendar events are derived from OHLC timestamps only (no external feed).

Read-only harness — no trading, no config.yaml changes.

Usage
-----
.. code-block:: powershell

    python scripts/event_study_calendar.py --calendar-flag weekend_start
    python scripts/event_study_calendar.py --calendar-flag us_open --ticker BTC
    python scripts/event_study_calendar.py --micro-baselines --days 730 \\
        --ohlc-source cache --use-cache-only \\
        --output-json reports/research_runs_phase11/calendar_micro_baselines.json
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _event_study_common import (  # noqa: E402
    DEFAULT_ALPHA,
    DEFAULT_DAYS,
    DEFAULT_N_PLACEBOS,
    DEFAULT_SEED,
    DEFAULT_WINDOWS,
    add_common_event_study_args,
    align_events_to_daily_candles,
    fetch_daily_ohlc_from_args,
    run_event_study_pipeline,
    write_json_report,
)
from src.crypto_ohlc_rest import CryptoOHLCFetchError
from src.research.event_study import EventStudyWindow, run_event_study
from src.research.placebo import (
    benjamini_hochberg,
    empirical_p_value,
    random_events_from_candles,
    shift_events_in_time,
)
from src.research.tradeability import (
    apply_economic_verdict_overlay,
    build_leaderboard_economic_overlay,
)
from src.signals.calendar_effects import (
    CALENDAR_EFFECT_DAILY_ALIASES,
    PRE_REGISTERED_CALENDAR_EFFECTS,
    build_asia_session_open_events,
    build_calendar_boundary_events,
    build_pre_registered_calendar_events,
    build_us_core_session_open_events,
    build_weekend_end_events,
    build_weekend_start_events,
    calendar_effects_for_event_study,
    is_calendar_effect_alias,
    placebo_timezone_for_effect,
    random_same_weekday_placebo_events,
)

TAG = "calendar"

_BUILDERS = {
    "weekend_start": build_weekend_start_events,
    "weekend_end": build_weekend_end_events,
    "us_open": build_us_core_session_open_events,
    "asia_open": build_asia_session_open_events,
}

PHASE11_METRICS = ("return", "realized_vol", "volume_ratio")
SHIFTED_CALENDAR_MIN_DAYS = 14
SHIFTED_CALENDAR_MAX_DAYS = 60
PHASE11_MIN_EVENTS = 5

_EFFECT_DESCRIPTIONS: dict[str, str] = {
    "us_market_open_window": "US equity weekday (Mon–Fri ET) daily candle",
    "sunday_us_evening": "Sunday calendar day America/New_York (daily OHLC)",
    "monday_asia_open": "Monday calendar day Asia/Tokyo (daily OHLC)",
    "third_friday": "Third Friday UTC (options expiry calendar proxy)",
    "month_end": "Last UTC calendar day with a candle each month",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Event study: calendar/session boundaries from daily OHLC "
            "vs forward returns (read-only, no external feed)."
        ),
    )
    add_common_event_study_args(p, default_ticker="BTC")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--calendar-flag",
        choices=tuple(_BUILDERS.keys()) + ("combined",),
        default="weekend_start",
        help=(
            "Which calendar event set to test (default weekend_start). "
            "combined=weekend_start+us_open via build_calendar_boundary_events."
        ),
    )
    mode.add_argument(
        "--micro-baselines",
        action="store_true",
        help=(
            "Run all five Phase 11 pre-registered calendar micro-baselines "
            f"({', '.join(PRE_REGISTERED_CALENDAR_EFFECTS)})."
        ),
    )
    return p.parse_args()


def _build_events(candles: list[dict], flag: str) -> list[int]:
    if flag == "combined":
        return build_calendar_boundary_events(candles, flags=("weekend_start", "us_open"))
    builder = _BUILDERS[flag]
    if flag in ("weekend_start", "weekend_end"):
        return builder(candles, use_utc=True)
    return builder(candles)


def compute_phase11_verdict(
    *,
    n_events: int,
    bh_rejected: int,
    raw_p_values: Sequence[float],
    economic_reject: bool,
    min_events: int = PHASE11_MIN_EVENTS,
) -> str:
    """Conservative Phase 11 classification (research-only)."""
    if n_events == 0:
        return "blocked"
    if n_events < min_events:
        return "blocked"
    if bh_rejected >= 1:
        if economic_reject:
            return "weak evidence"
        return "candidate for further OOS testing only"
    if any(p < 0.05 for p in raw_p_values):
        return "weak evidence"
    if economic_reject:
        return "kill"
    return "kill"


def _placebo_replicate_metric(
    *,
    candles: list[dict[str, Any]],
    events: list[int],
    window: EventStudyWindow,
    metric_name: str,
) -> float | None:
    if not events:
        return None
    result = run_event_study(
        candles,
        events=events,
        windows=[window],
        metrics=[metric_name],
        compute_baseline=False,
    )
    row = result.row(metric_name, window.label)
    if row is None or row.n_events == 0:
        return None
    return float(row.mean)


def _bootstrap_placebo_p(
    *,
    candles: list[dict[str, Any]],
    events: list[int],
    observed_mean: float,
    window: EventStudyWindow,
    metric_name: str,
    n_placebos: int,
    seed: int,
    placebo_builder,
) -> float | None:
    placebo_values: list[float] = []
    for i in range(n_placebos):
        placebo_events = placebo_builder(int(seed) + i)
        val = _placebo_replicate_metric(
            candles=candles,
            events=placebo_events,
            window=window,
            metric_name=metric_name,
        )
        if val is not None:
            placebo_values.append(val)
    if not placebo_values:
        return None
    return empirical_p_value(observed=observed_mean, placebo_values=placebo_values).two_sided


def run_single_micro_baseline(
    *,
    effect_id: str,
    candles: list[dict[str, Any]],
    n_placebos: int,
    seed: int,
    alpha: float,
    ticker: str,
    window_days: int,
) -> dict[str, Any]:
    """Run one pre-registered calendar effect with dual calendar placebos."""
    raw_events = build_pre_registered_calendar_events(candles, effect_id)
    events = align_events_to_daily_candles(raw_events, candles)
    hypothesis = (
        f"calendar {effect_id} ({_EFFECT_DESCRIPTIONS[effect_id]}) -> "
        f"forward {ticker} return/vol/volume"
    )

    result = run_event_study(
        candles,
        events=events,
        windows=list(DEFAULT_WINDOWS),
        metrics=list(PHASE11_METRICS),
        compute_baseline=True,
    )

    bh_input: list[tuple[str, str, float, float, int, float]] = []
    placebo_tz = placebo_timezone_for_effect(effect_id)
    candle_ts = [int(c["timestamp"]) for c in candles]

    reference_window = EventStudyWindow("post_7", 1, 7)
    reference_metric = "return"

    placebo_notes: dict[str, Any] = {
        "random_bootstrap": f"{n_placebos} reps, seed {seed} (uniform random candles)",
        "same_weekday": (
            f"{n_placebos} reps, random candles sharing event weekday in "
            f"{placebo_tz.key if hasattr(placebo_tz, 'key') else placebo_tz}"
        ),
        "shifted_calendar": (
            f"{n_placebos} reps, random +{SHIFTED_CALENDAR_MIN_DAYS}.."
            f"+{SHIFTED_CALENDAR_MAX_DAYS}d shift aligned to candles"
        ),
    }

    same_weekday_ps: list[float] = []
    shifted_ps: list[float] = []

    for metric_name in PHASE11_METRICS:
        for window in DEFAULT_WINDOWS:
            row = result.row(metric_name, window.label)
            if row is None or row.n_events == 0:
                continue

            bootstrap_values: list[float] = []
            for i in range(n_placebos):
                placebo_events = random_events_from_candles(
                    candle_ts,
                    n_events=row.n_events,
                    seed=int(seed) + i,
                )
                val = _placebo_replicate_metric(
                    candles=candles,
                    events=placebo_events,
                    window=window,
                    metric_name=metric_name,
                )
                if val is not None:
                    bootstrap_values.append(val)

            if not bootstrap_values:
                continue

            p = empirical_p_value(observed=row.mean, placebo_values=bootstrap_values).two_sided
            bh_input.append(
                (
                    metric_name,
                    window.label,
                    row.mean,
                    result.baseline.get(metric_name, float("nan")),
                    row.n_events,
                    p,
                )
            )

            if metric_name == reference_metric and window.label == reference_window.label:
                sw_p = _bootstrap_placebo_p(
                    candles=candles,
                    events=events,
                    observed_mean=row.mean,
                    window=window,
                    metric_name=metric_name,
                    n_placebos=n_placebos,
                    seed=seed + 50_000,
                    placebo_builder=lambda sub_seed: random_same_weekday_placebo_events(
                        candle_ts,
                        events,
                        tz=placebo_tz,
                        seed=sub_seed,
                    ),
                )
                if sw_p is not None:
                    same_weekday_ps.append(sw_p)

                def _shifted_builder(sub_seed: int) -> list[int]:
                    rng = random.Random(sub_seed)
                    delta_days = rng.randint(
                        SHIFTED_CALENDAR_MIN_DAYS,
                        SHIFTED_CALENDAR_MAX_DAYS,
                    )
                    shifted = shift_events_in_time(
                        events,
                        delta_seconds=delta_days * 86_400,
                    )
                    return align_events_to_daily_candles(shifted, candles)

                sh_p = _bootstrap_placebo_p(
                    candles=candles,
                    events=events,
                    observed_mean=row.mean,
                    window=window,
                    metric_name=metric_name,
                    n_placebos=n_placebos,
                    seed=seed + 100_000,
                    placebo_builder=_shifted_builder,
                )
                if sh_p is not None:
                    shifted_ps.append(sh_p)

    raw_ps = [p for *_rest, p in bh_input]
    bh_rejected = 0
    bh = None
    if bh_input:
        bh = benjamini_hochberg(raw_ps, alpha=alpha)
        bh_rejected = bh.n_rejected

    interim_verdict = "blocked" if len(events) < PHASE11_MIN_EVENTS else "kill"
    if len(events) >= PHASE11_MIN_EVENTS:
        if bh_rejected >= 1:
            interim_verdict = "candidate for further OOS testing only"
        elif any(p < 0.05 for p in raw_ps):
            interim_verdict = "weak evidence"

    report: dict[str, Any] = {
        "effect_id": effect_id,
        "description": _EFFECT_DESCRIPTIONS[effect_id],
        "hypothesis": hypothesis,
        "verdict": interim_verdict,
        "events_count": len(events),
        "events_used": result.events_used,
        "events_skipped_oob": result.events_skipped_oob,
        "candles_count": len(candles),
        "n_placebos": n_placebos,
        "seed": seed,
        "alpha": alpha,
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
        "placebo_notes": placebo_notes,
        "placebo_same_weekday_return_post_7_p": (
            same_weekday_ps[0] if same_weekday_ps else None
        ),
        "placebo_shifted_calendar_return_post_7_p": (
            shifted_ps[0] if shifted_ps else None
        ),
        "ticker": ticker,
        "window_days": window_days,
    }
    if bh is not None:
        report["bh_rejected"] = bh.n_rejected
        report["bh_q_values"] = list(bh.q_values)
        report["bh_rejected_mask"] = list(bh.rejected)

    overlay = build_leaderboard_economic_overlay(
        report,
        bh_supported=bh_rejected >= 1,
        oos_confirmed=False,
    )
    report["economic_overlay"] = overlay.as_dict()

    final_verdict = compute_phase11_verdict(
        n_events=len(events),
        bh_rejected=bh_rejected,
        raw_p_values=raw_ps,
        economic_reject=overlay.economic_reject,
    )
    rejection_reason: str | None = None
    if overlay.economic_reject:
        rejection_reason = overlay.economic_reject_reason
    if (
        same_weekday_ps
        and same_weekday_ps[0] < 0.05
        and bh_rejected == 0
        and final_verdict == "kill"
    ):
        final_verdict = "weak evidence"
        rejection_reason = (
            (rejection_reason + "; ") if rejection_reason else ""
        ) + "same-weekday placebo p<0.05 without FDR support"

    final_verdict, rejection_reason = apply_economic_verdict_overlay(
        final_verdict,
        rejection_reason,
        overlay,
    )
    if final_verdict == "candidate for OOS retest":
        final_verdict = "candidate for further OOS testing only"

    report["verdict"] = final_verdict
    if rejection_reason:
        report["rejection_reason"] = rejection_reason

    return report


def run_micro_baselines(
    *,
    candles: list[dict[str, Any]],
    n_placebos: int,
    seed: int,
    alpha: float,
    ticker: str,
    window_days: int,
) -> dict[str, Any]:
    """Run distinct pre-registered calendar micro-baselines (aliases skipped)."""
    effects: list[dict[str, Any]] = []
    summary: dict[str, str] = {}
    alias_records: list[dict[str, Any]] = []

    runnable = calendar_effects_for_event_study()
    for alias_id, canonical in CALENDAR_EFFECT_DAILY_ALIASES.items():
        canonical_events = build_pre_registered_calendar_events(candles, canonical)
        alias_events = build_pre_registered_calendar_events(candles, alias_id)
        alias_records.append(
            {
                "alias_effect_id": alias_id,
                "canonical_effect_id": canonical,
                "skipped": True,
                "timestamps_identical": canonical_events == alias_events,
            }
        )
        summary[alias_id] = f"alias_of:{canonical}"

    for idx, effect_id in enumerate(runnable):
        effect_seed = int(seed) + idx * 10_000
        report = run_single_micro_baseline(
            effect_id=effect_id,
            candles=candles,
            n_placebos=n_placebos,
            seed=effect_seed,
            alpha=alpha,
            ticker=ticker,
            window_days=window_days,
        )
        if is_calendar_effect_alias(effect_id):
            report["alias_skipped"] = True
        effects.append(report)
        summary[effect_id] = report["verdict"]
        print(f"[{TAG}] {effect_id}: {report['events_count']} events -> {report['verdict']}")

    return {
        "phase": 12,
        "suite": "calendar_micro_baselines",
        "pre_registered_effects": list(PRE_REGISTERED_CALENDAR_EFFECTS),
        "effects_run": list(runnable),
        "daily_aliases": alias_records,
        "ticker": ticker,
        "window_days": window_days,
        "n_placebos": n_placebos,
        "seed": seed,
        "alpha": alpha,
        "metrics": list(PHASE11_METRICS),
        "placebo_protocol": [
            "random_bootstrap (200 reps default)",
            "random_same_weekday (return/post_7)",
            "shifted_calendar +14..+60d (return/post_7)",
        ],
        "verdict_summary": summary,
        "effects": effects,
    }


def main() -> int:
    args = parse_args()

    try:
        candles = fetch_daily_ohlc_from_args(args)
    except CryptoOHLCFetchError as exc:
        print(f"[{TAG}] FATAL Kraken OHLC failed: {exc}", file=sys.stderr)
        return 3
    if not candles:
        print(f"[{TAG}] FATAL 0 candles", file=sys.stderr)
        return 3
    print(f"[{TAG}] {args.ticker} daily OHLC: {len(candles)} candles")

    if args.micro_baselines:
        report = run_micro_baselines(
            candles=candles,
            n_placebos=args.n_placebos,
            seed=args.seed,
            alpha=args.alpha,
            ticker=args.ticker,
            window_days=args.days,
        )
        out_path = args.output_json or (
            _REPO_ROOT / "reports" / "research_runs_phase11" / "calendar_micro_baselines.json"
        )
        write_json_report(out_path, report, tag=TAG)
        return 0

    hypothesis = (
        f"calendar {args.calendar_flag} boundary -> "
        f"forward {args.ticker} return/vol"
    )

    events = _build_events(candles, args.calendar_flag)
    print(f"[{TAG}] calendar events ({args.calendar_flag}): {len(events)}")

    code, report = run_event_study_pipeline(
        tag=TAG,
        hypothesis=hypothesis,
        candles=candles,
        events=events,
        n_placebos=args.n_placebos,
        seed=args.seed,
        alpha=args.alpha,
    )
    report.update(
        {
            "calendar_flag": args.calendar_flag,
            "ticker": args.ticker,
            "window_days": args.days,
        }
    )

    if args.output_json:
        write_json_report(args.output_json, report, tag=TAG)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
