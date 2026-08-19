"""Shared helpers for ``scripts/event_study_*.py`` (read-only research harness).

Not imported by production trading code. Mirrors
:mod:`scripts.demo_event_study` patterns: placebo bootstrap, BH-FDR,
honest verdict strings.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.crypto_ohlc_rest import (
    fetch_crypto_ohlc_paginated,
    normalize_crypto_pair,
)
from src.data.collectors._provenance import (
    DataProvenance,
    merge_provenance_into_report,
    provenance_from_cache_path,
)
from src.data.collectors.binance_public import (
    default_ohlc_daily_cache_path,
    fetch_ohlc_daily_cache_only,
    fetch_ohlc_daily_with_cache,
)
from src.research.event_study import EventStudyWindow, run_event_study
from src.research.holdout import DEFAULT_HOLDOUT_FRACTION, evaluate_holdout_g4
from src.research.placebo import (
    benjamini_hochberg,
    empirical_p_value,
    random_events_from_candles,
)

DEFAULT_DAYS = 180
DEFAULT_N_PLACEBOS = 200
DEFAULT_SEED = 20260519
DEFAULT_ALPHA = 0.05
DEFAULT_METRICS = ("return", "realized_vol")
DEFAULT_WINDOWS = (
    EventStudyWindow("post_1", 1, 1),
    EventStudyWindow("post_3", 1, 3),
    EventStudyWindow("post_7", 1, 7),
)

OHLC_SOURCE_KRAKEN = "kraken"
OHLC_SOURCE_CACHE = "cache"
OHLC_SOURCE_BINANCE = "binance-public"
OHLC_SOURCE_CHOICES = (OHLC_SOURCE_KRAKEN, OHLC_SOURCE_CACHE, OHLC_SOURCE_BINANCE)

COLLECTOR_CACHE_README = REPO_ROOT / "data" / "collector_cache" / "README.md"


def _console_text(text: str) -> str:
    """Avoid Windows cp1252 console crashes on Unicode arrows."""
    return text.replace("\u2192", "->")


def cache_only_hint(cache_path: Path, *, feed_name: str) -> str:
    """Short stderr suffix when ``--use-cache-only`` hits a missing feed."""
    return (
        f"With --use-cache-only, populate {feed_name} at {cache_path} "
        f"(run without the flag once, or see {COLLECTOR_CACHE_README})."
    )


def add_common_event_study_args(
    p: argparse.ArgumentParser,
    *,
    default_ticker: str = "BTC",
    default_days: int = DEFAULT_DAYS,
) -> None:
    """Register CLI flags shared by all event-study scripts."""
    p.add_argument(
        "--days",
        type=int,
        default=default_days,
        help=f"Look-back window in days (default {default_days}).",
    )
    p.add_argument(
        "--ticker",
        type=str,
        default=default_ticker,
        help=f"Crypto ticker for Kraken public OHLC (default {default_ticker!r}).",
    )
    p.add_argument(
        "--n-placebos",
        type=int,
        default=DEFAULT_N_PLACEBOS,
        help=f"Placebo bootstrap replicates (default {DEFAULT_N_PLACEBOS}).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Master seed for placebo bootstrap (default {DEFAULT_SEED}).",
    )
    p.add_argument(
        "--alpha",
        type=float,
        default=DEFAULT_ALPHA,
        help=f"Target FDR for Benjamini-Hochberg (default {DEFAULT_ALPHA}).",
    )
    p.add_argument(
        "--use-cache-only",
        action="store_true",
        help="Do not perform live HTTP for signal feeds (cache must cover the window).",
    )
    p.add_argument(
        "--ohlc-source",
        choices=OHLC_SOURCE_CHOICES,
        default=OHLC_SOURCE_KRAKEN,
        help=(
            "Daily OHLC provider: kraken (~720 REST candles), cache "
            "(data/collector_cache/ohlc_daily_{TICKER}.json), or "
            "binance-public (paginated klines, optional cache persist)."
        ),
    )
    p.add_argument(
        "--ohlc-cache-path",
        type=Path,
        default=None,
        help=(
            "Override path for --ohlc-source cache (default "
            "data/collector_cache/ohlc_daily_{TICKER}.json)."
        ),
    )
    p.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write the full JSON report.",
    )
    p.add_argument(
        "--enable-holdout",
        action="store_true",
        help="Run G4 temporal hold-out (last fraction of candles = test).",
    )
    p.add_argument(
        "--holdout-fraction",
        type=float,
        default=DEFAULT_HOLDOUT_FRACTION,
        help=f"Test-window fraction when --enable-holdout (default {DEFAULT_HOLDOUT_FRACTION}).",
    )


def fetch_daily_ohlc(
    ticker: str,
    days: int,
    *,
    ohlc_source: str = OHLC_SOURCE_KRAKEN,
    ohlc_cache_path: Path | None = None,
    use_cache_only: bool = False,
) -> list[dict[str, Any]]:
    """Pull daily OHLC for event studies (Kraken, cache, or Binance public)."""
    source = ohlc_source.strip().lower()
    cache_path = ohlc_cache_path or default_ohlc_daily_cache_path(ticker)

    if source == OHLC_SOURCE_CACHE:
        return fetch_ohlc_daily_cache_only(
            ticker, days, cache_path=cache_path
        )

    if source == OHLC_SOURCE_BINANCE:
        return fetch_ohlc_daily_with_cache(
            ticker,
            days,
            cache_path=cache_path,
            use_cache_only=use_cache_only,
        )

    if source != OHLC_SOURCE_KRAKEN:
        raise ValueError(
            f"unsupported ohlc_source {ohlc_source!r}; "
            f"expected one of {OHLC_SOURCE_CHOICES}"
        )

    if use_cache_only:
        return fetch_ohlc_daily_cache_only(
            ticker, days, cache_path=cache_path
        )

    pair = normalize_crypto_pair(ticker)
    since = int((datetime.now(UTC) - timedelta(days=days + 5)).timestamp())
    target_candles = max(days + 10, 30)
    rows = fetch_crypto_ohlc_paginated(
        pair,
        interval_min=1440,
        target_candles=target_candles,
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


def fetch_daily_ohlc_from_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Resolve OHLC from ``add_common_event_study_args`` namespace."""
    return fetch_daily_ohlc(
        args.ticker,
        args.days,
        ohlc_source=getattr(args, "ohlc_source", OHLC_SOURCE_KRAKEN),
        ohlc_cache_path=getattr(args, "ohlc_cache_path", None),
        use_cache_only=bool(getattr(args, "use_cache_only", False)),
    )


def align_events_to_daily_candles(
    raw_events: Sequence[int],
    candles: Sequence[dict[str, Any]],
) -> list[int]:
    """Map event timestamps to the daily candle on the same UTC calendar day."""
    candle_by_day: dict[str, int] = {}
    for c in candles:
        ts = int(c["timestamp"])
        day = datetime.fromtimestamp(ts, tz=UTC).date().isoformat()
        candle_by_day[day] = ts

    aligned: list[int] = []
    seen: set[int] = set()
    for ev in raw_events:
        day = datetime.fromtimestamp(int(ev), tz=UTC).date().isoformat()
        ct = candle_by_day.get(day)
        if ct is None or ct in seen:
            continue
        seen.add(ct)
        aligned.append(ct)
    return sorted(aligned)


def _placebo_replicate_metric(
    *,
    candles: list[dict[str, Any]],
    n_events: int,
    window: EventStudyWindow,
    metric_name: str,
    sub_seed: int,
) -> float | None:
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


def compute_verdict(
    *,
    bh_rejected: int,
    raw_p_values: Sequence[float],
    n_events: int,
    min_events: int = 5,
) -> str:
    """Return one of: supported / weak evidence / not supported, move on."""
    if n_events == 0:
        return "blocked: insufficient events"
    if n_events < min_events:
        return "weak evidence"
    if bh_rejected >= 1:
        return "supported"
    if any(p < 0.05 for p in raw_p_values):
        return "weak evidence"
    return "not supported, move on"


def run_event_study_pipeline(
    *,
    tag: str,
    hypothesis: str,
    candles: list[dict[str, Any]],
    events: list[int],
    n_placebos: int,
    seed: int,
    alpha: float,
    metrics: Sequence[str] = DEFAULT_METRICS,
    windows: Sequence[EventStudyWindow] = DEFAULT_WINDOWS,
) -> tuple[int, dict[str, Any]]:
    """Run study + placebo + BH; print table; return exit code and report dict."""
    print(_console_text(f"[{tag}] hypothesis: {hypothesis}"))
    print(
        _console_text(
            f"[{tag}] events aligned to daily candles: {len(events)} "
            f"({len(events) / max(len(candles), 1):.1%} of candles)"
        )
    )
    if len(events) < 5:
        print(
            _console_text(
                f"[{tag}] WARNING fewer than 5 events — statistical power is "
                "negligible."
            )
        )

    result = run_event_study(
        candles,
        events=events,
        windows=list(windows),
        metrics=list(metrics),
        compute_baseline=True,
    )
    print(
        _console_text(
            f"[{tag}] event study: {result.events_used} used, "
            f"{result.events_skipped_oob} skipped at boundary"
        )
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
            for i in range(n_placebos):
                val = _placebo_replicate_metric(
                    candles=candles,
                    n_events=row.n_events,
                    window=window,
                    metric_name=metric_name,
                    sub_seed=int(seed) + i,
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

    bh_rejected = 0
    bh = None
    raw_ps: list[float] = []
    if bh_input:
        raw_ps = [p for *_rest, p in bh_input]
        bh = benjamini_hochberg(raw_ps, alpha=alpha)
        bh_rejected = bh.n_rejected
        print()
        print(
            _console_text(
                f"[{tag}] Benjamini-Hochberg at FDR={alpha}: "
                f"{bh.n_rejected}/{len(raw_ps)} cells reject H0"
            )
        )

    verdict = compute_verdict(
        bh_rejected=bh_rejected,
        raw_p_values=raw_ps,
        n_events=len(events),
    )
    print(_console_text(f"[{tag}] VERDICT: {verdict}"))

    report: dict[str, Any] = {
        "hypothesis": hypothesis,
        "verdict": verdict,
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
    }
    if bh is not None:
        report["bh_rejected"] = bh.n_rejected
        report["bh_q_values"] = list(bh.q_values)
        report["bh_rejected_mask"] = list(bh.rejected)

    return 0, report


def attach_holdout_to_report(
    report: dict[str, Any],
    *,
    candles: list[dict[str, Any]],
    events: list[int],
    metrics: Sequence[str] = DEFAULT_METRICS,
    windows: Sequence[EventStudyWindow] = DEFAULT_WINDOWS,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
    embargo_days: int = 0,
    n_placebos: int = DEFAULT_N_PLACEBOS,
    seed: int = DEFAULT_SEED,
    alpha: float = DEFAULT_ALPHA,
    reference_metric: str = "return",
    reference_window: str = "post_7",
) -> dict[str, Any]:
    """Evaluate G4 hold-out and attach ``holdout`` block; cap OOS labels if fail."""
    evaluation = evaluate_holdout_g4(
        candles,
        events,
        metrics=metrics,
        windows=windows,
        holdout_fraction=holdout_fraction,
        embargo_days=embargo_days,
        n_placebos=n_placebos,
        seed=seed,
        alpha=alpha,
        reference_metric=reference_metric,
        reference_window=reference_window,
    )
    report = dict(report)
    report["holdout"] = evaluation.to_dict()
    if not evaluation.oos_survives:
        for key in ("phase11_final_verdict", "phase11_verdict", "research_verdict"):
            if report.get(key) in (
                "candidate for further OOS testing",
                "candidate for OOS",
                "candidate for OOS retest",
            ):
                report[key] = "weak evidence"
        verdict = report.get("verdict")
        if verdict in (
            "candidate for further OOS testing",
            "candidate for OOS",
            "candidate for OOS retest",
            "supported",
        ):
            report["verdict"] = "weak evidence"
        extra = evaluation.failure_reason or "hold-out failed"
        prev = report.get("rejection_reason")
        report["rejection_reason"] = f"{prev}; {extra}" if prev else extra
    return report


def attach_provenance(
    report: dict[str, Any],
    *,
    ohlc_cache_path: Path | None = None,
    signal_cache_path: Path | None = None,
    ohlc_source: str | None = None,
) -> dict[str, Any]:
    ohlc_prov: DataProvenance | None = None
    if ohlc_cache_path is not None:
        ohlc_prov = provenance_from_cache_path(
            ohlc_cache_path, source=ohlc_source or "cache"
        )
    signal_prov: DataProvenance | None = None
    if signal_cache_path is not None:
        signal_prov = provenance_from_cache_path(signal_cache_path, source="cache")
    return merge_provenance_into_report(
        report, ohlc=ohlc_prov, signal=signal_prov
    )


def write_json_report(path: Path, report: dict[str, Any], *, tag: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(_console_text(f"[{tag}] full report written to {path}"))


def window_iso_range(days: int) -> tuple[str, str, datetime.date]:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days)
    return start.isoformat(), today.isoformat(), today


__all__ = [
    "REPO_ROOT",
    "DEFAULT_DAYS",
    "DEFAULT_N_PLACEBOS",
    "DEFAULT_SEED",
    "DEFAULT_WINDOWS",
    "OHLC_SOURCE_BINANCE",
    "OHLC_SOURCE_CACHE",
    "OHLC_SOURCE_CHOICES",
    "OHLC_SOURCE_KRAKEN",
    "add_common_event_study_args",
    "fetch_daily_ohlc",
    "fetch_daily_ohlc_from_args",
    "align_events_to_daily_candles",
    "compute_verdict",
    "run_event_study_pipeline",
    "attach_holdout_to_report",
    "attach_provenance",
    "write_json_report",
    "window_iso_range",
]
