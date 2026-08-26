"""Run preregistered Kraken microstructure hypothesis H-KM-001.

Validation is deliberately separated from the final 2026 holdout.  The final
stage refuses to run unless the validation artifact passed every preregistered
gate with the same preregistration hash.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.collectors._common import CollectorError, utc_now_iso  # noqa: E402
from src.data.collectors._provenance import (  # noqa: E402
    safe_git_commit,
    sha256_file,
)
from src.data.collectors.kraken_futures_charts import (  # noqa: E402
    fetch_analytics,
    fetch_candles,
)
from src.research.kraken_microstructure import (  # noqa: E402
    HOUR_SECONDS,
    align_market_bars,
    analyze_segment,
    build_feature_points,
    build_trade_outcomes,
    generate_signal_events,
)

SYMBOL = "PF_XBTUSD"
INTERVAL_SECONDS = HOUR_SECONDS
RESOLUTION = "1h"
FETCH_START = date(2023, 3, 8)
DEVELOPMENT_START = date(2023, 6, 1)
VALIDATION_START = date(2025, 1, 1)
FINAL_START = date(2026, 1, 1)
VALIDATION_END_EXCLUSIVE = FINAL_START
REQUIRED_ANALYTICS = (
    "open-interest",
    "liquidation-volume",
    "aggressor-differential",
)
PREREGISTRATION_PATH = Path("docs/KRAKEN_MICROSTRUCTURE_PREREGISTRATION.md")
DEFAULT_CACHE_DIR = Path("data/collector_cache/kraken_futures_charts")
DEFAULT_OUTPUT_DIR = Path("reports/kraken_microstructure_hkm001")
SOURCE_CODE_PATHS = (
    Path("scripts/run_kraken_microstructure_hkm001.py"),
    Path("src/data/collectors/kraken_futures_charts.py"),
    Path("src/research/kraken_microstructure.py"),
)


def _unix_start(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())


def _iso_day(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _cache_path(
    cache_dir: Path,
    *,
    symbol: str,
    series: str,
    since: int,
    to: int,
) -> Path:
    safe_series = series.replace("-", "_")
    return cache_dir / (
        f"{symbol}_{RESOLUTION}_{safe_series}_{_iso_day(since)}_{_iso_day(to - 1)}.json"
    )


def _load_cache(
    path: Path,
    *,
    symbol: str,
    series: str,
    since: int,
    to: int,
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorError(f"unreadable cache {path}: {exc}") from exc
    expected = {
        "symbol": symbol,
        "series": series,
        "interval_seconds": INTERVAL_SECONDS,
        "since": since,
        "to": to,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise CollectorError(
                f"cache metadata mismatch {path}: {key}={payload.get(key)!r}, expected {value!r}"
            )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise CollectorError(f"cache {path} is missing rows[]")
    return [dict(row) for row in rows if isinstance(row, dict)]


def _fetch_or_load(
    *,
    cache_dir: Path,
    symbol: str,
    series: str,
    since: int,
    to: int,
    refresh: bool,
    cache_only: bool,
) -> tuple[list[dict[str, Any]], Path, str]:
    path = _cache_path(
        cache_dir,
        symbol=symbol,
        series=series,
        since=since,
        to=to,
    )
    if path.is_file() and not refresh:
        return (
            _load_cache(
                path,
                symbol=symbol,
                series=series,
                since=since,
                to=to,
            ),
            path,
            "cache",
        )
    if cache_only:
        raise CollectorError(f"cache-only mode: missing exact cache {path}")

    if series == "candles":
        rows = fetch_candles(
            symbol,
            RESOLUTION,
            since=since,
            to=to,
        )
        source_url = (
            f"https://futures.kraken.com/api/charts/v1/trade/{symbol}/{RESOLUTION}"
        )
    else:
        rows = fetch_analytics(
            symbol,
            series,
            interval_seconds=INTERVAL_SECONDS,
            since=since,
            to=to,
        )
        source_url = (
            f"https://futures.kraken.com/api/charts/v1/analytics/{symbol}/{series}"
        )
    payload = {
        "schema_version": "hkm001-v1",
        "source_url": source_url,
        "symbol": symbol,
        "series": series,
        "interval_seconds": INTERVAL_SECONDS,
        "since": since,
        "to": to,
        "fetched_at": utc_now_iso(),
        "row_count": len(rows),
        "rows": rows,
    }
    _atomic_write_json(path, payload)
    return rows, path, "network"


def _coverage(
    rows: list[dict[str, Any]], segment_start: int, segment_end: int
) -> dict[str, Any]:
    expected_timestamps = set(range(segment_start, segment_end, INTERVAL_SECONDS))
    timestamps = {
        int(row["timestamp"])
        for row in rows
        if isinstance(row.get("timestamp"), int)
        and segment_start <= int(row["timestamp"]) < segment_end
    }
    off_grid = sorted(ts for ts in timestamps if ts not in expected_timestamps)
    missing = sorted(expected_timestamps - timestamps)
    return {
        "expected": len(expected_timestamps),
        "observed": len(timestamps),
        "coverage": (
            len(timestamps & expected_timestamps) / len(expected_timestamps)
            if expected_timestamps
            else 0.0
        ),
        "missing_count": len(missing),
        "off_grid_count": len(off_grid),
        "first_missing": missing[0] if missing else None,
        "first_off_grid": off_grid[0] if off_grid else None,
    }


def _data_bundle(
    *,
    cache_dir: Path,
    end_exclusive: date,
    refresh: bool,
    cache_only: bool,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    since = _unix_start(FETCH_START)
    to = _unix_start(end_exclusive)
    bundle: dict[str, list[dict[str, Any]]] = {}
    provenance: dict[str, Any] = {}
    for series in ("candles", *REQUIRED_ANALYTICS):
        rows, path, mode = _fetch_or_load(
            cache_dir=cache_dir,
            symbol=SYMBOL,
            series=series,
            since=since,
            to=to,
            refresh=refresh,
            cache_only=cache_only,
        )
        bundle[series] = rows
        provenance[series] = {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "row_count": len(rows),
            "load_mode": mode,
        }
    return bundle, provenance


def _quality_report(
    bundle: dict[str, list[dict[str, Any]]],
    alignment: dict[str, int],
    *,
    start: int,
    end: int,
) -> dict[str, Any]:
    coverage = {
        series: _coverage(rows, start, end) for series, rows in bundle.items()
    }
    common_expected = max(0, (end - start) // INTERVAL_SECONDS)
    expected_timestamps = set(range(start, end, INTERVAL_SECONDS))
    timestamp_sets = {
        series: {
            int(row["timestamp"])
            for row in rows
            if isinstance(row.get("timestamp"), int)
        }
        for series, rows in bundle.items()
    }
    common_timestamps = set.intersection(*timestamp_sets.values())
    common_valid = len(common_timestamps & expected_timestamps)
    common_coverage = common_valid / common_expected if common_expected else 0.0
    passed = (
        all(float(item["coverage"]) >= 0.95 for item in coverage.values())
        and all(int(item["off_grid_count"]) == 0 for item in coverage.values())
        and common_coverage >= 0.95
        and alignment.get("invalid", 0) == 0
    )
    return {
        "passed": passed,
        "coverage": coverage,
        "common_expected": common_expected,
        "common_valid": common_valid,
        "common_coverage": common_coverage,
        "alignment": alignment,
    }


def _markdown(report: dict[str, Any]) -> str:
    validation = report["segments"]["validation"]
    primary = validation["microstructure"]
    gates = validation["gates"]
    lines = [
        "# H-KM-001 — résultat de validation",
        "",
        f"- Statut : **{report['status']}**",
        f"- Trades validation : **{primary['trade_count']}**",
        f"- PnL net validation : **{primary['pnl_usd']:.2f} USD**",
        f"- Win rate : **{(primary['win_rate'] or 0) * 100:.2f} %**",
        f"- Test final 2026 scellé : **{str(report['test_final_sealed']).lower()}**",
        "",
        "## Gates",
        "",
    ]
    for name, passed in gates.items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{name}`")
    lines.extend(
        [
            "",
            "Ce rapport est une sortie de recherche, pas un conseil financier ni une",
            "autorisation de trading paper/live.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(output_dir: Path, name: str, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(output_dir / f"{name}.json", report)
    (output_dir / f"{name}.md").write_text(_markdown(report), encoding="utf-8")


def _validation_artifact(output_dir: Path) -> Path:
    return output_dir / "validation.json"


def _assert_final_unlocked(output_dir: Path, prereg_hash: str | None) -> dict[str, Any]:
    path = _validation_artifact(output_dir)
    if not path.is_file():
        raise RuntimeError("final stage is sealed: validation.json is missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    validation = payload.get("segments", {}).get("validation", {})
    gates = validation.get("gates", {})
    if (
        payload.get("stage") != "validation"
        or payload.get("status") != "validation_pass"
        or validation.get("passed") is not True
        or not gates
        or not all(value is True for value in gates.values())
    ):
        raise RuntimeError("final stage is sealed: validation did not pass every gate")
    if payload.get("preregistration_sha256") != prereg_hash:
        raise RuntimeError("final stage is sealed: preregistration hash changed")
    current_source_hashes = {
        str(path): sha256_file(path) for path in SOURCE_CODE_PATHS
    }
    if payload.get("source_code_sha256") != current_source_hashes:
        raise RuntimeError("final stage is sealed: research harness changed")
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.refresh and args.cache_only:
        raise ValueError("--refresh and --cache-only are mutually exclusive")
    prereg_hash = sha256_file(PREREGISTRATION_PATH)
    if prereg_hash is None:
        raise RuntimeError(f"missing preregistration: {PREREGISTRATION_PATH}")

    if args.stage == "validation":
        end_exclusive = VALIDATION_END_EXCLUSIVE
        previous_validation = None
    else:
        previous_validation = _assert_final_unlocked(args.output_dir, prereg_hash)
        requested_end = date.fromisoformat(args.end_date)
        if requested_end < FINAL_START:
            raise ValueError("--end-date must be within the final 2026 holdout")
        end_exclusive = requested_end + timedelta(days=1)

    bundle, provenance = _data_bundle(
        cache_dir=args.cache_dir,
        end_exclusive=end_exclusive,
        refresh=args.refresh,
        cache_only=args.cache_only,
    )
    bars, alignment = align_market_bars(
        bundle["candles"],
        bundle["open-interest"],
        bundle["liquidation-volume"],
        bundle["aggressor-differential"],
    )
    points = build_feature_points(bars)
    micro_events, baseline_events, signal_diagnostics = generate_signal_events(points)

    development_start = _unix_start(DEVELOPMENT_START)
    validation_start = _unix_start(VALIDATION_START)
    final_start = _unix_start(FINAL_START)
    validation_end = final_start
    quality = _quality_report(
        bundle,
        alignment,
        start=validation_start,
        end=validation_end,
    )
    development_micro = build_trade_outcomes(
        micro_events,
        bars,
        segment_start=development_start,
        segment_end=validation_start,
    )
    development_baseline = build_trade_outcomes(
        baseline_events,
        bars,
        segment_start=development_start,
        segment_end=validation_start,
    )
    validation_micro = build_trade_outcomes(
        micro_events,
        bars,
        segment_start=validation_start,
        segment_end=validation_end,
    )
    validation_baseline = build_trade_outcomes(
        baseline_events,
        bars,
        segment_start=validation_start,
        segment_end=validation_end,
    )
    development_points = sum(
        development_start <= point.timestamp < validation_start for point in points
    )
    validation_points = sum(
        validation_start <= point.timestamp < validation_end for point in points
    )
    segments: dict[str, Any] = {
        "development": analyze_segment(
            development_micro,
            development_baseline,
            segment_start=development_start,
            segment_end=validation_start,
            eligible_bar_count=development_points,
            data_quality_passed=True,
        ),
        "validation": analyze_segment(
            validation_micro,
            validation_baseline,
            segment_start=validation_start,
            segment_end=validation_end,
            eligible_bar_count=validation_points,
            data_quality_passed=bool(quality["passed"]),
        ),
    }
    validation_passed = bool(segments["validation"]["passed"])
    status = "validation_pass" if validation_passed else segments["validation"]["status"]
    test_final_sealed = not validation_passed

    if args.stage == "final":
        final_end = _unix_start(end_exclusive)
        final_quality = _quality_report(
            bundle,
            alignment,
            start=final_start,
            end=final_end,
        )
        final_micro = build_trade_outcomes(
            micro_events,
            bars,
            segment_start=final_start,
            segment_end=final_end,
        )
        final_baseline = build_trade_outcomes(
            baseline_events,
            bars,
            segment_start=final_start,
            segment_end=final_end,
        )
        final_points = sum(final_start <= point.timestamp < final_end for point in points)
        segments["final"] = analyze_segment(
            final_micro,
            final_baseline,
            segment_start=final_start,
            segment_end=final_end,
            eligible_bar_count=final_points,
            data_quality_passed=bool(final_quality["passed"]),
        )
        both_pass = validation_passed and bool(segments["final"]["passed"])
        status = "candidate_for_forward_observation" if both_pass else segments["final"]["status"]
        test_final_sealed = False
        quality["final"] = final_quality

    report = {
        "schema_version": "hkm001-report-v1",
        "generated_at": utc_now_iso(),
        "stage": args.stage,
        "status": status,
        "symbol": SYMBOL,
        "resolution": RESOLUTION,
        "preregistration": str(PREREGISTRATION_PATH),
        "preregistration_sha256": prereg_hash,
        "git_commit": safe_git_commit(),
        "source_code_sha256": {
            str(path): sha256_file(path) for path in SOURCE_CODE_PATHS
        },
        "data_end_exclusive": end_exclusive.isoformat(),
        "test_final_sealed": test_final_sealed,
        "previous_validation_sha256": sha256_file(_validation_artifact(args.output_dir))
        if previous_validation is not None
        else None,
        "cost_model": {
            "primary_round_trip_bps": 35,
            "taker_fee_each_side_bps": 5,
            "slippage_each_side_bps": 10,
            "funding_buffer_bps": 5,
            "fee_source": "https://support.kraken.com/articles/360048917612-fee-schedule",
        },
        "source_docs": {
            "candles": "https://docs.kraken.com/api/docs/futures-api/charts/candles",
            "analytics": "https://docs.kraken.com/api/docs/futures-api/charts/market-analytics",
        },
        "data_provenance": provenance,
        "data_quality": quality,
        "signal_diagnostics": signal_diagnostics,
        "segments": segments,
    }
    _write_report(args.output_dir, args.stage, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("validation", "final"), default="validation")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument(
        "--end-date",
        default=(datetime.now(UTC).date() - timedelta(days=1)).isoformat(),
        help="last complete UTC day for --stage final",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run(args)
    except (CollectorError, RuntimeError, ValueError) as exc:
        print(f"H-KM-001 blocked: {exc}", file=sys.stderr)
        return 2
    validation = report["segments"]["validation"]["microstructure"]
    print(
        f"H-KM-001 {report['stage']}: {report['status']} | "
        f"validation trades={validation['trade_count']} "
        f"pnl_usd={validation['pnl_usd']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
