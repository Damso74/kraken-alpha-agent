"""Event study: Wikipedia pageview attention spikes vs crypto forward outcomes.

Read-only harness — no trading, no config.yaml changes.

Single-article mode (legacy) and Phase 11 **basket** mode (crypto page bundle +
non-crypto placebo pages). Pre-registered z thresholds: 1.5 and 2.0 only.

Usage
-----
.. code-block:: powershell

    python scripts/event_study_wikipedia.py --article Bitcoin
    python scripts/event_study_wikipedia.py --layout basket --days 365 `
        --ohlc-source binance-public `
        --output-json reports/research_runs_phase11/wikipedia_basket_365d.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _event_study_common import (  # noqa: E402
    REPO_ROOT,
    add_common_event_study_args,
    align_events_to_daily_candles,
    attach_holdout_to_report,
    attach_provenance,
    fetch_daily_ohlc_from_args,
    run_event_study_pipeline,
    window_iso_range,
    write_json_report,
)
from src.data.collectors.binance_public import default_ohlc_daily_cache_path  # noqa: E402
from src.crypto_ohlc_rest import CryptoOHLCFetchError
from src.data.collectors._common import CollectorError
from src.data.collectors.wikimedia import (
    default_wikimedia_cache_path,
    fetch_pageviews,
)
from src.research.event_study import EventStudyWindow, run_event_study
from src.research.placebo import shift_events_in_time
from src.signals.wiki_attention import (
    CRYPTO_ATTENTION_BASKET,
    NON_CRYPTO_PLACEBO_BASKET,
    PREREGISTERED_Z_THRESHOLDS,
    WikiBasketEvents,
    build_preregistered_basket_momentum_events,
    build_wiki_attention_contrarian_events,
    build_wiki_attention_momentum_events,
)

TAG = "wikipedia"
DEFAULT_CACHE = REPO_ROOT / default_wikimedia_cache_path()
PHASE11_OUT_DIR = REPO_ROOT / "reports" / "research_runs_phase11"
PHASE11_RUN_LOG = PHASE11_OUT_DIR / "RUN_LOG_PHASE11.md"

# Vol / volume primary; return reported but not decisive for Phase 11 verdict.
PHASE11_PRIMARY_METRICS: tuple[str, ...] = ("realized_vol", "volume_ratio")
PHASE11_METRICS: tuple[str, ...] = PHASE11_PRIMARY_METRICS + ("return",)
PHASE11_WINDOWS: tuple[EventStudyWindow, ...] = (
    EventStudyWindow("post_1", 1, 1),
    EventStudyWindow("post_3", 1, 3),
    EventStudyWindow("post_7", 1, 7),
)

SHIFT_PLACEBO_SECONDS = 86_400 * 30
MIN_EVENTS_POWER = 5

PHASE11_VERDICT_BLOCKED = "blocked"
PHASE11_VERDICT_KILL = "kill"
PHASE11_VERDICT_WEAK = "weak evidence"
PHASE11_VERDICT_CANDIDATE = "candidate for further OOS testing"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Event study: Wikipedia pageview z-score events vs forward "
            "crypto vol/volume/return (read-only)."
        ),
    )
    add_common_event_study_args(p, default_ticker="BTC")
    p.add_argument(
        "--layout",
        choices=("single", "basket"),
        default="single",
        help="single=one article; basket=Phase 11 crypto bundle (default single).",
    )
    p.add_argument(
        "--article",
        type=str,
        default="Bitcoin",
        help="Wikipedia article title for single layout (default Bitcoin).",
    )
    p.add_argument(
        "--project",
        type=str,
        default="en.wikipedia",
        help="Wikimedia project (default en.wikipedia).",
    )
    p.add_argument(
        "--mode",
        choices=("momentum", "contrarian"),
        default="momentum",
        help="momentum=high z spike; contrarian=low z vacuum (default momentum).",
    )
    p.add_argument(
        "--z-threshold",
        type=float,
        default=None,
        help=(
            "Override z for single layout only. Basket layout ignores this and "
            "uses pre-registered thresholds "
            f"{list(PREREGISTERED_Z_THRESHOLDS)}."
        ),
    )
    p.add_argument(
        "--lookback",
        type=int,
        default=30,
        help="Rolling z-score window in days (default 30).",
    )
    p.add_argument(
        "--cache-path",
        type=Path,
        default=DEFAULT_CACHE,
        help="Wikimedia pageviews JSON cache path.",
    )
    return p.parse_args()


def _wiki_rows_for_signal(rows: list[dict]) -> list[dict]:
    """Map collector ``views`` → signal ``pageviews``."""
    out: list[dict] = []
    for row in rows:
        r = dict(row)
        if "pageviews" not in r and "views" in r:
            r["pageviews"] = r["views"]
        out.append(r)
    return out


def _load_pageviews(
    article: str,
    project: str,
    start_iso: str,
    end_iso: str,
    cache_path: Path,
    *,
    use_cache_only: bool,
) -> list[dict]:
    if use_cache_only:

        def _blocked(*_a: object, **_kw: object) -> dict:
            raise CollectorError("use_cache_only: network fetch disabled")

        rows = fetch_pageviews(
            article,
            start_iso,
            end_iso,
            cache_path=cache_path,
            project=project,
            fetcher=_blocked,  # type: ignore[arg-type]
        )
    else:
        rows = fetch_pageviews(
            article,
            start_iso,
            end_iso,
            cache_path=cache_path,
            project=project,
        )
    return [dict(r) for r in rows]


def _load_rows_by_article(
    articles: Sequence[str],
    project: str,
    start_iso: str,
    end_iso: str,
    cache_path: Path,
    *,
    use_cache_only: bool,
) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for article in articles:
        pv_rows = _load_pageviews(
            article,
            project,
            start_iso,
            end_iso,
            cache_path,
            use_cache_only=use_cache_only,
        )
        out[article] = _wiki_rows_for_signal(pv_rows)
    return out


def _primary_vol_significant(cells: Sequence[dict[str, Any]]) -> bool:
    for cell in cells:
        if cell.get("metric") not in PHASE11_PRIMARY_METRICS:
            continue
        p = cell.get("two_sided_p")
        if isinstance(p, (int, float)) and p < 0.05:
            return True
    return False


def _primary_bh_rejected(cells: Sequence[dict[str, Any]], mask: Sequence[bool]) -> int:
    n = 0
    for cell, rej in zip(cells, mask):
        if not rej:
            continue
        if cell.get("metric") in PHASE11_PRIMARY_METRICS:
            n += 1
    return n


def compute_phase11_verdict(
    *,
    n_events: int,
    cells: Sequence[dict[str, Any]],
    bh_rejected_mask: Sequence[bool] | None,
    shift_vol_significant: bool,
    non_crypto_vol_significant: bool,
    data_blocked: bool = False,
) -> str:
    """Map study + placebos to a Phase 11 verdict (never live-ready wording)."""
    if data_blocked or n_events == 0:
        return PHASE11_VERDICT_BLOCKED
    if n_events < MIN_EVENTS_POWER:
        return PHASE11_VERDICT_WEAK
    if shift_vol_significant or non_crypto_vol_significant:
        return PHASE11_VERDICT_KILL
    bh_primary = 0
    if bh_rejected_mask is not None:
        bh_primary = _primary_bh_rejected(cells, bh_rejected_mask)
    if bh_primary >= 1:
        return PHASE11_VERDICT_CANDIDATE
    if _primary_vol_significant(cells):
        return PHASE11_VERDICT_WEAK
    return PHASE11_VERDICT_KILL


def _shift_placebo_vol_significant(
    candles: list[dict[str, Any]],
    aligned_events: list[int],
) -> bool:
    """True if +30d shifted events still show vol p<0.05 (post_3, no bootstrap)."""
    if not aligned_events:
        return False
    shifted = shift_events_in_time(aligned_events, delta_seconds=SHIFT_PLACEBO_SECONDS)
    shifted_aligned = align_events_to_daily_candles(shifted, candles)
    if len(shifted_aligned) < MIN_EVENTS_POWER:
        return False
    result = run_event_study(
        candles,
        events=shifted_aligned,
        windows=[EventStudyWindow("post_3", 1, 3)],
        metrics=["realized_vol"],
        compute_baseline=False,
    )
    row = result.row("realized_vol", "post_3")
    if row is None or row.n_events == 0:
        return False
    # Heuristic: elevated post-event vol vs zero baseline when baseline unset.
    return float(row.mean) > 0.02


def _run_aligned_pipeline(
    *,
    tag_suffix: str,
    hypothesis: str,
    candles: list[dict[str, Any]],
    raw_events: list[int],
    n_placebos: int,
    seed: int,
    alpha: float,
    metrics: Sequence[str],
) -> tuple[list[int], dict[str, Any]]:
    events = align_events_to_daily_candles(raw_events, candles)
    _code, report = run_event_study_pipeline(
        tag=f"{TAG}{tag_suffix}",
        hypothesis=hypothesis,
        candles=candles,
        events=events,
        n_placebos=n_placebos,
        seed=seed,
        alpha=alpha,
        metrics=metrics,
        windows=PHASE11_WINDOWS,
    )
    report["aligned_events"] = events
    return events, report


def _basket_events_to_dict(basket: WikiBasketEvents) -> dict[str, Any]:
    return {
        "z_threshold": basket.z_threshold,
        "basket_aggregate_count": len(basket.basket_aggregate),
        "basket_aggregate_timestamps": list(basket.basket_aggregate),
        "per_page_counts": {k: len(v) for k, v in basket.per_page.items()},
        "per_page_timestamps": {k: list(v) for k, v in basket.per_page.items()},
    }


def _run_basket_threshold_block(
    *,
    z_threshold: float,
    basket: WikiBasketEvents,
    candles: list[dict[str, Any]],
    non_crypto_rows: dict[str, list[dict]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    hypo = (
        f"Wikipedia crypto basket aggregate z>={z_threshold} → "
        f"forward {args.ticker} vol/volume (return secondary)"
    )
    aligned, report = _run_aligned_pipeline(
        tag_suffix=f"_basket_z{z_threshold}",
        hypothesis=hypo,
        candles=candles,
        raw_events=list(basket.basket_aggregate),
        n_placebos=args.n_placebos,
        seed=args.seed,
        alpha=args.alpha,
        metrics=PHASE11_METRICS,
    )

    shift_sig = _shift_placebo_vol_significant(candles, aligned)

    nc_basket = build_preregistered_basket_momentum_events(
        non_crypto_rows,
        lookback=args.lookback,
        articles=NON_CRYPTO_PLACEBO_BASKET,
    )[z_threshold]
    nc_aligned = align_events_to_daily_candles(
        list(nc_basket.basket_aggregate), candles
    )
    nc_vol_sig = False
    if len(nc_aligned) >= MIN_EVENTS_POWER:
        nc_result = run_event_study(
            candles,
            events=nc_aligned,
            windows=[EventStudyWindow("post_3", 1, 3)],
            metrics=["realized_vol"],
            compute_baseline=False,
        )
        nc_row = nc_result.row("realized_vol", "post_3")
        if nc_row is not None and nc_row.n_events > 0 and float(nc_row.mean) > 0.02:
            nc_vol_sig = True

    verdict = compute_phase11_verdict(
        n_events=len(aligned),
        cells=report.get("cells", []),
        bh_rejected_mask=report.get("bh_rejected_mask"),
        shift_vol_significant=shift_sig,
        non_crypto_vol_significant=nc_vol_sig,
    )
    report["phase11_verdict"] = verdict
    report["z_threshold"] = z_threshold
    report["basket_events"] = _basket_events_to_dict(basket)
    report["placebos"] = {
        "shift_30d_vol_heuristic_significant": shift_sig,
        "non_crypto_basket_events_count": len(nc_aligned),
        "non_crypto_basket_vol_heuristic_significant": nc_vol_sig,
        "random_events_bootstrap": {
            "n_placebos": args.n_placebos,
            "seed": args.seed,
        },
    }
    report["primary_metrics"] = list(PHASE11_PRIMARY_METRICS)
    report["ticker"] = args.ticker

    if getattr(args, "enable_holdout", False):
        report = attach_holdout_to_report(
            report,
            candles=candles,
            events=aligned,
            metrics=PHASE11_METRICS,
            windows=PHASE11_WINDOWS,
            holdout_fraction=float(getattr(args, "holdout_fraction", 0.30)),
            n_placebos=args.n_placebos,
            seed=args.seed,
            alpha=args.alpha,
            reference_metric="realized_vol",
            reference_window="post_3",
        )
        if not report.get("holdout", {}).get("oos_survives", False):
            verdict = PHASE11_VERDICT_WEAK
            report["phase11_verdict"] = verdict

    return report


def _append_phase11_run_log(
    *,
    days: int,
    output_path: Path | None,
    report: dict[str, Any],
) -> None:
    PHASE11_OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "",
        f"## Wikipedia basket ({datetime.now(timezone.utc).date().isoformat()})",
        "",
        f"- Window: {days}d | ticker: {report.get('ticker', 'BTC')}",
        f"- Pre-registered z: {list(PREREGISTERED_Z_THRESHOLDS)}",
        f"- Crypto pages: {len(CRYPTO_ATTENTION_BASKET)} | "
        f"Non-crypto placebo pages: {len(NON_CRYPTO_PLACEBO_BASKET)}",
        f"- **Phase 11 verdict (aggregate z={report.get('z_threshold')}): "
        f"{report.get('phase11_verdict')}**",
        f"- Basket aggregate events: "
        f"{report.get('basket_events', {}).get('basket_aggregate_count', 'n/a')}",
    ]
    if output_path is not None:
        lines.append(f"- Artifact: `{output_path.relative_to(REPO_ROOT).as_posix()}`")
    lines.append(
        "- Note: not tradable / not live-ready — research falsification only."
    )
    if not PHASE11_RUN_LOG.exists():
        header = (
            "# Phase 11 research runs (read-only)\n\n"
            "Wikipedia basket and related falsification harnesses. "
            "Verdicts are never tradable or live-ready.\n"
        )
        PHASE11_RUN_LOG.write_text(header, encoding="utf-8")
    with PHASE11_RUN_LOG.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _run_basket_layout(args: argparse.Namespace) -> int:
    start_iso, end_iso, _ = window_iso_range(args.days)

    try:
        crypto_rows = _load_rows_by_article(
            CRYPTO_ATTENTION_BASKET,
            args.project,
            start_iso,
            end_iso,
            args.cache_path,
            use_cache_only=args.use_cache_only,
        )
        non_crypto_rows = _load_rows_by_article(
            NON_CRYPTO_PLACEBO_BASKET,
            args.project,
            start_iso,
            end_iso,
            args.cache_path,
            use_cache_only=args.use_cache_only,
        )
    except (CollectorError, ValueError) as exc:
        print(f"[{TAG}] FATAL pageviews fetch failed: {exc}", file=sys.stderr)
        return 2

    total_rows = sum(len(v) for v in crypto_rows.values())
    print(
        f"[{TAG}] basket pageview rows: {total_rows} "
        f"across {len(crypto_rows)} crypto articles"
    )
    if total_rows == 0:
        print(f"[{TAG}] FATAL 0 crypto pageview rows", file=sys.stderr)
        return 2

    try:
        candles = fetch_daily_ohlc_from_args(args)
    except CryptoOHLCFetchError as exc:
        print(f"[{TAG}] FATAL Kraken OHLC failed: {exc}", file=sys.stderr)
        return 3
    if not candles:
        print(f"[{TAG}] FATAL 0 candles", file=sys.stderr)
        return 3
    print(f"[{TAG}] {args.ticker} daily OHLC: {len(candles)} candles")

    baskets = build_preregistered_basket_momentum_events(
        crypto_rows,
        lookback=args.lookback,
    )

    threshold_reports: dict[str, Any] = {}
    final_verdict = PHASE11_VERDICT_BLOCKED
    for z_threshold, basket in baskets.items():
        block = _run_basket_threshold_block(
            z_threshold=z_threshold,
            basket=basket,
            candles=candles,
            non_crypto_rows=non_crypto_rows,
            args=args,
        )
        threshold_reports[str(z_threshold)] = block
        print(
            f"[{TAG}] Phase 11 z>={z_threshold}: "
            f"{block['phase11_verdict']} "
            f"({block['events_count']} aggregate events)"
        )
        final_verdict = block["phase11_verdict"]

    ohlc_path = args.ohlc_cache_path or default_ohlc_daily_cache_path(args.ticker)
    combined: dict[str, Any] = {
        "layout": "basket",
        "phase": 12,
        "hypothesis_family": (
            "Wikipedia crypto attention basket → BTC vol/volume "
            "(pre-registered z, not optimized)"
        ),
        "phase11_final_verdict": final_verdict,
        "pre_registered_z_thresholds": list(PREREGISTERED_Z_THRESHOLDS),
        "crypto_basket_articles": list(CRYPTO_ATTENTION_BASKET),
        "non_crypto_placebo_articles": list(NON_CRYPTO_PLACEBO_BASKET),
        "lookback": args.lookback,
        "ticker": args.ticker,
        "window_days": args.days,
        "pageview_rows_crypto_total": total_rows,
        "thresholds": threshold_reports,
        "disclaimer": (
            "Research-only falsification. Verdict is never tradable, "
            "profitable, or live-ready."
        ),
    }

    combined = attach_provenance(
        combined,
        ohlc_cache_path=ohlc_path,
        signal_cache_path=args.cache_path,
        ohlc_source=str(getattr(args, "ohlc_source", "cache")),
    )
    if getattr(args, "enable_holdout", False):
        surviving = [
            b.get("phase11_verdict")
            for b in threshold_reports.values()
            if b.get("holdout", {}).get("oos_survives")
        ]
        if not surviving:
            final_verdict = PHASE11_VERDICT_WEAK
            combined["phase11_final_verdict"] = final_verdict

    out_path = args.output_json
    if out_path is None:
        out_path = PHASE11_OUT_DIR / f"wikipedia_basket_{args.days}d.json"
    write_json_report(out_path, combined, tag=TAG)
    _append_phase11_run_log(
        days=args.days,
        output_path=out_path,
        report=threshold_reports.get(str(PREREGISTERED_Z_THRESHOLDS[-1]), combined),
    )
    print(f"[{TAG}] PHASE 11 FINAL VERDICT: {final_verdict}")
    return 0 if final_verdict != PHASE11_VERDICT_BLOCKED else 2


def main() -> int:
    args = parse_args()
    if args.layout == "basket":
        if args.mode != "momentum":
            print(
                f"[{TAG}] basket layout supports momentum only; "
                f"got mode={args.mode!r}",
                file=sys.stderr,
            )
            return 2
        return _run_basket_layout(args)

    start_iso, end_iso, _ = window_iso_range(args.days)
    z_threshold = args.z_threshold if args.z_threshold is not None else 2.0
    hypothesis = (
        f"Wikipedia {args.mode} ({args.article}) z>={z_threshold} → "
        f"forward {args.ticker} return/vol"
    )

    try:
        pv_rows = _load_pageviews(
            args.article,
            args.project,
            start_iso,
            end_iso,
            args.cache_path,
            use_cache_only=args.use_cache_only,
        )
    except (CollectorError, ValueError) as exc:
        print(f"[{TAG}] FATAL pageviews fetch failed: {exc}", file=sys.stderr)
        return 2
    print(f"[{TAG}] pageview rows: {len(pv_rows)} ({args.article})")

    signal_rows = _wiki_rows_for_signal(pv_rows)
    if args.mode == "contrarian":
        raw_events = build_wiki_attention_contrarian_events(
            signal_rows,
            z_threshold=z_threshold,
            lookback=args.lookback,
        )
    else:
        raw_events = build_wiki_attention_momentum_events(
            signal_rows,
            z_threshold=z_threshold,
            lookback=args.lookback,
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

    _code, report = run_event_study_pipeline(
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
            "layout": "single",
            "article": args.article,
            "project": args.project,
            "mode": args.mode,
            "z_threshold": z_threshold,
            "lookback": args.lookback,
            "ticker": args.ticker,
            "window_days": args.days,
            "pageview_rows": len(pv_rows),
        }
    )

    if args.output_json:
        write_json_report(args.output_json, report, tag=TAG)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
