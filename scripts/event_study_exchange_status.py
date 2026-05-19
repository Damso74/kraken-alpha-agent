"""Event study: exchange status incidents vs crypto forward returns/vol.

Read-only harness — no trading, no config.yaml changes.

Usage
-----
.. code-block:: powershell

    python scripts/event_study_exchange_status.py
    python scripts/event_study_exchange_status.py --venue kraken --min-impact major
    python scripts/event_study_exchange_status.py --phase11-sprint --days 365 \\
        --ohlc-source binance-public --use-cache-only \\
        --output-json reports/research_runs_phase11/exchange_status_deep_dive_365d.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _event_study_common import (  # noqa: E402
    REPO_ROOT,
    _placebo_replicate_metric,
    add_common_event_study_args,
    align_events_to_daily_candles,
    fetch_daily_ohlc_from_args,
    run_event_study_pipeline,
    write_json_report,
)
from src.crypto_ohlc_rest import CryptoOHLCFetchError
from src.data.collectors._common import CollectorError
from src.data.collectors.status_pages import (
    default_status_cache_path,
    fetch_all_status_incidents,
    fetch_status_incidents,
)
from src.research.event_study import EventStudyWindow, run_event_study
from src.research.placebo import empirical_p_value, shift_events_in_time
from src.signals.exchange_status import (
    build_exchange_status_events,
    classify_incident_kind,
    count_rows_by_impact,
    count_rows_by_kind,
    incident_duration_minutes,
)

TAG = "exchange_status"
DEFAULT_CACHE = REPO_ROOT / default_status_cache_path()
PHASE11_OUT_DIR = REPO_ROOT / "reports" / "research_runs_phase11"
SHIFT_PLACEBO_DAYS = 14
MIN_EVENTS_G0 = 5
MIN_EVENTS_EXCHANGE_DOC = 10

PHASE11_WINDOWS = (
    EventStudyWindow("post_1", 1, 1),
    EventStudyWindow("post_3", 1, 3),
)
PRIMARY_METRICS = ("realized_vol",)
SECONDARY_METRICS = ("return",)

# Pre-registered Phase 11 variants (no post-hoc optimization).
PHASE11_VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "variant_id": "unscheduled_incidents",
        "label": "Unscheduled incidents only (minor+)",
        "incident_kind": "unscheduled",
        "min_impact": "minor",
        "venue": "all",
    },
    {
        "variant_id": "scheduled_maintenance",
        "label": "Scheduled maintenance separate (minor+)",
        "incident_kind": "scheduled",
        "min_impact": "minor",
        "venue": "all",
    },
    {
        "variant_id": "impact_minor",
        "label": "Impact tier: minor only",
        "impact_exact": "minor",
        "incident_kind": "all",
        "venue": "all",
    },
    {
        "variant_id": "impact_major",
        "label": "Impact tier: major only",
        "impact_exact": "major",
        "incident_kind": "all",
        "venue": "all",
    },
    {
        "variant_id": "impact_critical",
        "label": "Impact tier: critical only",
        "impact_exact": "critical",
        "incident_kind": "all",
        "venue": "all",
    },
    {
        "variant_id": "duration_gt_30m",
        "label": "Duration > 30 minutes (minor+, parseable span)",
        "min_duration_minutes": 30.0,
        "min_impact": "minor",
        "incident_kind": "all",
        "venue": "all",
    },
    {
        "variant_id": "venue_kraken",
        "label": "Kraken only (minor+)",
        "min_impact": "minor",
        "incident_kind": "all",
        "venue": "kraken",
    },
    {
        "variant_id": "venue_coinbase",
        "label": "Coinbase only (minor+)",
        "min_impact": "minor",
        "incident_kind": "all",
        "venue": "coinbase",
    },
    {
        "variant_id": "basket_combined",
        "label": "Combined Kraken + Coinbase basket (minor+)",
        "min_impact": "minor",
        "incident_kind": "all",
        "venue": "all",
    },
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Event study: Statuspage exchange incidents vs forward "
            "crypto returns/vol (read-only)."
        ),
    )
    add_common_event_study_args(p, default_ticker="BTC")
    p.add_argument(
        "--venue",
        choices=("all", "kraken", "coinbase"),
        default="all",
        help="Statuspage venue filter (default all).",
    )
    p.add_argument(
        "--min-impact",
        choices=("minor", "major", "critical"),
        default="major",
        help="Minimum incident impact tier (default major).",
    )
    p.add_argument(
        "--cache-path",
        type=Path,
        default=DEFAULT_CACHE,
        help="Statuspage incidents JSON cache path.",
    )
    p.add_argument(
        "--phase11-sprint",
        action="store_true",
        help=(
            "Run pre-registered Phase 11 deep-dive variants; writes "
            "diagnostics + conservative verdicts (never tradable)."
        ),
    )
    return p.parse_args()


def _rows_for_signal(incident_rows: list[dict]) -> list[dict]:
    """Map collector ``venue`` → signal ``provider``; default component."""
    out: list[dict] = []
    for row in incident_rows:
        r = dict(row)
        if "provider" not in r and "venue" in r:
            r["provider"] = r["venue"]
        r.setdefault("component", "trading")
        out.append(r)
    return out


def _load_incidents(
    venue: str,
    cache_path: Path,
    *,
    use_cache_only: bool,
) -> list[dict]:
    if use_cache_only:

        def _blocked(_v: str) -> dict:
            raise CollectorError("use_cache_only: network fetch disabled")

        if venue == "all":
            rows = fetch_all_status_incidents(
                cache_path=cache_path, fetcher=_blocked  # type: ignore[arg-type]
            )
        else:
            rows = fetch_status_incidents(
                venue, cache_path=cache_path, fetcher=_blocked  # type: ignore[arg-type]
            )
    else:
        if venue == "all":
            rows = fetch_all_status_incidents(cache_path=cache_path)
        else:
            rows = fetch_status_incidents(venue, cache_path=cache_path)
    return [dict(r) for r in rows]


def _filter_rows_in_ohlc_window(
    rows: Sequence[Mapping[str, Any]],
    candles: Sequence[Mapping[str, Any]],
) -> list[dict]:
    if not candles:
        return list(rows)
    start_ts = min(int(c["timestamp"]) for c in candles)
    end_ts = max(int(c["timestamp"]) for c in candles)
    return [dict(r) for r in rows if start_ts <= int(r["timestamp"]) <= end_ts]


def _build_events_for_variant(
    signal_rows: Sequence[Mapping[str, Any]],
    spec: Mapping[str, Any],
) -> list[int]:
    venue = str(spec.get("venue", "all"))
    providers = None if venue == "all" else [venue]
    kwargs: dict[str, Any] = {
        "providers": providers,
        "incident_kind": spec.get("incident_kind", "all"),
    }
    if "impact_exact" in spec:
        kwargs["impact_exact"] = spec["impact_exact"]
    else:
        kwargs["min_impact"] = spec.get("min_impact", "minor")
    if "min_duration_minutes" in spec:
        kwargs["min_duration_minutes"] = float(spec["min_duration_minutes"])
    return build_exchange_status_events(signal_rows, **kwargs)


def _variant_diagnostics(
    signal_rows: Sequence[Mapping[str, Any]],
    spec: Mapping[str, Any],
    *,
    raw_events: Sequence[int],
    aligned_events: Sequence[int],
) -> dict[str, Any]:
    durations = [incident_duration_minutes(r) for r in signal_rows]
    known = [d for d in durations if d is not None]
    return {
        "variant_id": spec["variant_id"],
        "label": spec.get("label", spec["variant_id"]),
        "filters": {
            k: spec[k]
            for k in (
                "incident_kind",
                "min_impact",
                "impact_exact",
                "min_duration_minutes",
                "venue",
            )
            if k in spec
        },
        "rows_in_ohlc_window": len(signal_rows),
        "rows_by_impact": count_rows_by_impact(signal_rows),
        "rows_by_kind": count_rows_by_kind(signal_rows),
        "duration_minutes": {
            "parseable": len(known),
            "gt_30": sum(1 for d in known if d > 30.0),
            "median": float(sorted(known)[len(known) // 2]) if known else None,
        },
        "raw_events": len(raw_events),
        "aligned_events": len(aligned_events),
        "g0_insufficient": len(aligned_events) < MIN_EVENTS_G0,
        "exchange_doc_insufficient": len(aligned_events) < MIN_EVENTS_EXCHANGE_DOC,
    }


def compute_phase11_verdict(
    *,
    n_events: int,
    bh_rejected_primary: int,
    raw_p_primary: Sequence[float],
    blocked: bool = False,
) -> str:
    """Conservative Phase 11 verdict (never implies tradability)."""
    if blocked:
        return "blocked"
    if n_events == 0:
        return "kill"
    if n_events < MIN_EVENTS_G0:
        return "weak evidence"
    if n_events < MIN_EVENTS_EXCHANGE_DOC:
        if bh_rejected_primary >= 1 or any(p < 0.05 for p in raw_p_primary):
            return "weak evidence"
        return "weak evidence"
    if bh_rejected_primary >= 1:
        return "candidate for OOS"
    if any(p < 0.05 for p in raw_p_primary):
        return "weak evidence"
    return "kill"


def _shift_placebo_p(
    *,
    candles: list[dict[str, Any]],
    events: list[int],
    metric: str,
    window: EventStudyWindow,
    n_placebos: int,
    seed: int,
) -> float | None:
    if not events:
        return None
    real = run_event_study(
        candles,
        events=events,
        windows=[window],
        metrics=[metric],
        compute_baseline=False,
    )
    real_row = real.row(metric, window.label)
    if real_row is None or real_row.n_events == 0:
        return None
    delta = SHIFT_PLACEBO_DAYS * 86_400
    shifted = shift_events_in_time(events, delta_seconds=delta)
    shifted_aligned = align_events_to_daily_candles(shifted, candles)
    if len(shifted_aligned) < len(events):
        return None
    shifted_result = run_event_study(
        candles,
        events=shifted_aligned,
        windows=[window],
        metrics=[metric],
        compute_baseline=False,
    )
    shifted_row = shifted_result.row(metric, window.label)
    if shifted_row is None or shifted_row.n_events == 0:
        return None
    placebo_values: list[float] = []
    for i in range(n_placebos):
        val = _placebo_replicate_metric(
            candles=candles,
            n_events=real_row.n_events,
            window=window,
            metric_name=metric,
            sub_seed=int(seed) + 10_000 + i,
        )
        if val is not None:
            placebo_values.append(val)
    if not placebo_values:
        return None
    p_real = empirical_p_value(observed=real_row.mean, placebo_values=placebo_values)
    p_shift = empirical_p_value(
        observed=shifted_row.mean, placebo_values=placebo_values
    )
    return float(p_shift.two_sided) if p_shift is not None else None


def _run_phase11_variant(
    *,
    spec: Mapping[str, Any],
    signal_rows: Sequence[Mapping[str, Any]],
    candles: list[dict[str, Any]],
    n_placebos: int,
    seed: int,
    alpha: float,
    ticker: str,
    window_days: int,
) -> dict[str, Any]:
    raw_events = _build_events_for_variant(signal_rows, spec)
    events = align_events_to_daily_candles(raw_events, candles)
    diag = _variant_diagnostics(
        signal_rows, spec, raw_events=raw_events, aligned_events=events
    )

    hypothesis = (
        f"Phase11 {spec['variant_id']}: {spec.get('label', '')} → "
        f"abnormal forward {ticker} realized_vol (primary) / return (secondary)"
    )

    _, report_primary = run_event_study_pipeline(
        tag=f"{TAG}/{spec['variant_id']}",
        hypothesis=hypothesis,
        candles=candles,
        events=events,
        n_placebos=n_placebos,
        seed=seed,
        alpha=alpha,
        metrics=list(PRIMARY_METRICS),
        windows=PHASE11_WINDOWS,
    )
    _, report_secondary = run_event_study_pipeline(
        tag=f"{TAG}/{spec['variant_id']}/return",
        hypothesis=hypothesis + " [secondary return]",
        candles=candles,
        events=events,
        n_placebos=n_placebos,
        seed=seed + 50_000,
        alpha=alpha,
        metrics=list(SECONDARY_METRICS),
        windows=PHASE11_WINDOWS,
    )

    primary_cells = report_primary.get("cells") or []
    primary_ps = [float(c["two_sided_p"]) for c in primary_cells]
    bh_primary = int(report_primary.get("bh_rejected") or 0)

    shift_ps: dict[str, float | None] = {}
    for window in PHASE11_WINDOWS:
        key = f"realized_vol_{window.label}"
        shift_ps[key] = _shift_placebo_p(
            candles=candles,
            events=events,
            metric="realized_vol",
            window=window,
            n_placebos=n_placebos,
            seed=seed,
        )

    verdict = compute_phase11_verdict(
        n_events=len(events),
        bh_rejected_primary=bh_primary,
        raw_p_primary=primary_ps,
    )

    return {
        "diagnostics": diag,
        "verdict": verdict,
        "tradable": False,
        "primary": {
            "metrics": list(PRIMARY_METRICS),
            "windows": [w.label for w in PHASE11_WINDOWS],
            "report": report_primary,
        },
        "secondary": {
            "metrics": list(SECONDARY_METRICS),
            "windows": [w.label for w in PHASE11_WINDOWS],
            "report": report_secondary,
        },
        "placebos": {
            "random_timestamps": {
                "n_replicates": n_placebos,
                "bh_rejected_primary": bh_primary,
                "cells": primary_cells,
            },
            "shift_plus_14d": {
                "delta_days": SHIFT_PLACEBO_DAYS,
                "two_sided_p": shift_ps,
            },
        },
    }


def _scheduled_vs_unscheduled_compare(
    signal_rows: Sequence[Mapping[str, Any]],
    candles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Placebo-style contrast: scheduled maintenance vs unscheduled incidents."""
    out: dict[str, Any] = {}
    for kind in ("scheduled", "unscheduled"):
        spec = {
            "variant_id": f"_{kind}_compare",
            "incident_kind": kind,
            "min_impact": "minor",
            "venue": "all",
        }
        raw = _build_events_for_variant(signal_rows, spec)
        aligned = align_events_to_daily_candles(raw, candles)
        if len(aligned) < MIN_EVENTS_G0:
            out[kind] = {"aligned_events": len(aligned), "means": {}}
            continue
        result = run_event_study(
            candles,
            events=aligned,
            windows=list(PHASE11_WINDOWS),
            metrics=["realized_vol"],
            compute_baseline=True,
        )
        means = {}
        for window in PHASE11_WINDOWS:
            row = result.row("realized_vol", window.label)
            means[window.label] = None if row is None else float(row.mean)
        out[kind] = {"aligned_events": len(aligned), "means": means}
    return out


def run_phase11_sprint(args: argparse.Namespace) -> int:
    """Execute all pre-registered variants and write the master JSON report."""
    try:
        incident_rows = _load_incidents(
            "all",
            args.cache_path,
            use_cache_only=args.use_cache_only,
        )
    except (CollectorError, ValueError) as exc:
        print(f"[{TAG}] FATAL incidents fetch failed: {exc}", file=sys.stderr)
        blocked_report = {
            "phase": 11,
            "agent": "exchange_status_deep_dive",
            "verdict_overall": "blocked",
            "tradable": False,
            "error": str(exc),
        }
        out = args.output_json or (
            PHASE11_OUT_DIR / f"exchange_status_deep_dive_{args.days}d.json"
        )
        write_json_report(out, blocked_report, tag=TAG)
        return 2

    try:
        candles = fetch_daily_ohlc_from_args(args)
    except CryptoOHLCFetchError as exc:
        print(f"[{TAG}] FATAL OHLC failed: {exc}", file=sys.stderr)
        return 3

    signal_rows = _rows_for_signal(incident_rows)
    signal_rows = _filter_rows_in_ohlc_window(signal_rows, candles)

    print(
        f"[{TAG}] Phase11 sprint: {len(incident_rows)} incident rows, "
        f"{len(signal_rows)} in OHLC window, {len(candles)} candles"
    )

    variants_out: list[dict[str, Any]] = []
    for spec in PHASE11_VARIANTS:
        print(f"[{TAG}] --- variant: {spec['variant_id']} ---")
        variants_out.append(
            _run_phase11_variant(
                spec=spec,
                signal_rows=signal_rows,
                candles=candles,
                n_placebos=args.n_placebos,
                seed=args.seed,
                alpha=args.alpha,
                ticker=args.ticker,
                window_days=args.days,
            )
        )

    scheduled_compare = _scheduled_vs_unscheduled_compare(signal_rows, candles)

    powered = [
        v
        for v in variants_out
        if int(v["diagnostics"]["aligned_events"]) >= MIN_EVENTS_G0
    ]
    if not powered:
        overall = "blocked"
    else:
        powered_verdicts = [str(v["verdict"]) for v in powered]
        if "candidate for OOS" in powered_verdicts:
            overall = "candidate for OOS"
        elif all(v == "kill" for v in powered_verdicts):
            overall = "kill"
        elif any(v == "weak evidence" for v in powered_verdicts):
            overall = "weak evidence"
        else:
            overall = "kill"

    master: dict[str, Any] = {
        "phase": 11,
        "agent": "exchange_status_deep_dive",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis_family": (
            "Exchange Statuspage incidents → forward BTC realized volatility "
            "(primary post_1/post_3) and return (secondary); never tradable."
        ),
        "verdict_overall": overall,
        "tradable": False,
        "rules": {
            "min_events_g0": MIN_EVENTS_G0,
            "min_events_exchange_doc": MIN_EVENTS_EXCHANGE_DOC,
            "few_events_large_effect": "weak evidence only",
            "tradability": "never",
        },
        "ticker": args.ticker,
        "window_days": args.days,
        "incident_rows_total": len(incident_rows),
        "incident_rows_in_ohlc_window": len(signal_rows),
        "candles_count": len(candles),
        "n_placebos": args.n_placebos,
        "seed": args.seed,
        "alpha": args.alpha,
        "variants": variants_out,
        "placebo_scheduled_vs_unscheduled": scheduled_compare,
    }

    out_path = args.output_json or (
        PHASE11_OUT_DIR / f"exchange_status_deep_dive_{args.days}d.json"
    )
    write_json_report(out_path, master, tag=TAG)
    print(f"[{TAG}] Phase11 overall verdict: {overall} (tradable=False)")
    return 0


def main() -> int:
    args = parse_args()

    if args.phase11_sprint:
        return run_phase11_sprint(args)

    hypothesis = (
        f"exchange status impact>={args.min_impact} ({args.venue}) → "
        f"abnormal forward {args.ticker} return/vol"
    )

    try:
        incident_rows = _load_incidents(
            args.venue,
            args.cache_path,
            use_cache_only=args.use_cache_only,
        )
    except (CollectorError, ValueError) as exc:
        print(f"[{TAG}] FATAL incidents fetch failed: {exc}", file=sys.stderr)
        return 2
    print(f"[{TAG}] incident rows: {len(incident_rows)}")

    providers = None if args.venue == "all" else [args.venue]
    raw_events = build_exchange_status_events(
        _rows_for_signal(incident_rows),
        min_impact=args.min_impact,
        providers=providers,
    )

    try:
        candles = fetch_daily_ohlc_from_args(args)
    except CryptoOHLCFetchError as exc:
        print(f"[{TAG}] FATAL Kraken OHLC failed: {exc}", file=sys.stderr)
        return 3
    if not candles:
        print(f"[{TAG}] FATAL 0 candles", file=sys.stderr)
        return 3
    print(f"[{TAG}] {args.ticker} daily OHLC: {len(candles)} candles")

    events = align_events_to_daily_candles(raw_events, candles)

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
            "venue": args.venue,
            "min_impact": args.min_impact,
            "incident_rows": len(incident_rows),
            "ticker": args.ticker,
            "window_days": args.days,
            "tradable": False,
        }
    )

    if args.output_json:
        write_json_report(args.output_json, report, tag=TAG)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
