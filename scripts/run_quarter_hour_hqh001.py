"""Run preregistered quarter-hour hypothesis H-QH-001.

The 2026 final holdout is checked for unlock before any final data is loaded.
This script uses public market data only and has no execution path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.collectors._common import CollectorError, utc_now_iso  # noqa: E402
from src.data.collectors._provenance import safe_git_commit, sha256_file  # noqa: E402
from src.data.collectors.kraken_futures_charts import (  # noqa: E402
    fetch_analytics,
    fetch_candles,
)
from src.research.quarter_hour import (  # noqa: E402
    FAMILY_ALPHA,
    MINUTE_SECONDS,
    PLACEBO_PHASE_MINUTE,
    PRIMARY_COST_BPS,
    PRIMARY_PHASE_MINUTE,
    STRESS_COST_BPS,
    align_minute_bars,
    analyze_segment,
    build_causal_weekly_thresholds,
    build_trade_outcomes,
    generate_events,
)

FETCH_START = date(2024, 7, 1)
VALIDATION_START = date(2025, 1, 1)
FINAL_START = date(2026, 1, 1)
VALIDATION_END_EXCLUSIVE = FINAL_START
PRIMARY_SYMBOL = "PF_XBTUSD"
REPLICATION_SYMBOL = "PF_ETHUSD"
RESOLUTION = "1m"
PREREGISTRATION_PATH = Path("docs/QUARTER_HOUR_PREREGISTRATION.md")
DEFAULT_CACHE_DIR = Path("data/collector_cache/quarter_hour_hqh001")
DEFAULT_OUTPUT_DIR = Path("reports/quarter_hour_hqh001")
SOURCE_CODE_PATHS = (
    Path("scripts/run_quarter_hour_hqh001.py"),
    Path("src/research/quarter_hour.py"),
    Path("src/data/collectors/kraken_futures_charts.py"),
)


def _unix_start(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())


def _iso_day(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(path)


def _cache_path(
    cache_dir: Path, *, symbol: str, series: str, since: int, to: int
) -> Path:
    return cache_dir / (
        f"{symbol}_{RESOLUTION}_{series.replace('-', '_')}_"
        f"{_iso_day(since)}_{_iso_day(to - 1)}.json"
    )


def _load_cache(
    path: Path, *, symbol: str, series: str, since: int, to: int
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorError(f"unreadable cache {path}: {exc}") from exc
    expected = {
        "schema_version": "hqh001-cache-v1",
        "symbol": symbol,
        "series": series,
        "interval_seconds": MINUTE_SECONDS,
        "since": since,
        "to": to,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise CollectorError(
                f"cache metadata mismatch {path}: {key}={payload.get(key)!r}, "
                f"expected {value!r}"
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
    path = _cache_path(cache_dir, symbol=symbol, series=series, since=since, to=to)
    if path.is_file() and not refresh:
        return (
            _load_cache(path, symbol=symbol, series=series, since=since, to=to),
            path,
            "cache",
        )
    if cache_only:
        raise CollectorError(f"cache-only mode: missing exact cache {path}")
    if series == "candles":
        rows = fetch_candles(symbol, RESOLUTION, since=since, to=to)
        source_url = f"https://futures.kraken.com/api/charts/v1/trade/{symbol}/{RESOLUTION}"
    else:
        rows = fetch_analytics(
            symbol,
            "aggressor-differential",
            interval_seconds=MINUTE_SECONDS,
            since=since,
            to=to,
        )
        source_url = (
            "https://futures.kraken.com/api/charts/v1/analytics/"
            f"{symbol}/aggressor-differential"
        )
    payload = {
        "schema_version": "hqh001-cache-v1",
        "source_url": source_url,
        "symbol": symbol,
        "series": series,
        "interval_seconds": MINUTE_SECONDS,
        "since": since,
        "to": to,
        "fetched_at": utc_now_iso(),
        "row_count": len(rows),
        "rows": rows,
    }
    _atomic_write_json(path, payload)
    return rows, path, "network"


def _data_bundle(
    *,
    cache_dir: Path,
    symbol: str,
    end_exclusive: date,
    refresh: bool,
    cache_only: bool,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    since = _unix_start(FETCH_START)
    to = _unix_start(end_exclusive)
    bundle: dict[str, list[dict[str, Any]]] = {}
    provenance: dict[str, Any] = {}
    for series in ("candles", "aggressor-differential"):
        rows, path, mode = _fetch_or_load(
            cache_dir=cache_dir,
            symbol=symbol,
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


def _coverage(rows: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    expected = set(range(start, end, MINUTE_SECONDS))
    timestamps = {
        int(row["timestamp"])
        for row in rows
        if isinstance(row.get("timestamp"), int) and start <= int(row["timestamp"]) < end
    }
    valid = timestamps & expected
    return {
        "expected": len(expected),
        "observed_on_grid": len(valid),
        "coverage": len(valid) / len(expected) if expected else 0.0,
        "missing_count": len(expected - timestamps),
        "off_grid_count": len(timestamps - expected),
    }


def _quality_report(
    bundle: dict[str, list[dict[str, Any]]],
    alignment: dict[str, int],
    threshold_diagnostics: dict[str, Any],
    *,
    start: int,
    end: int,
) -> dict[str, Any]:
    coverage = {
        name: _coverage(rows, start, end) for name, rows in bundle.items()
    }
    passed = (
        all(float(item["coverage"]) >= 0.99 for item in coverage.values())
        and all(int(item["off_grid_count"]) == 0 for item in coverage.values())
        and alignment.get("invalid", 0) == 0
        and alignment.get("off_grid", 0) == 0
        and threshold_diagnostics.get("weeks_expected")
        == threshold_diagnostics.get("weeks_with_threshold")
    )
    return {
        "passed": passed,
        "coverage": coverage,
        "alignment": alignment,
        "thresholds": threshold_diagnostics,
    }


def _source_hashes() -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in SOURCE_CODE_PATHS}


def _assert_artifact(
    path: Path,
    *,
    expected_stage: str,
    expected_status: str,
    prereg_hash: str,
) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"stage is sealed: {path} is missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    gates = payload.get("result", {}).get("gates", {})
    if (
        payload.get("stage") != expected_stage
        or payload.get("status") != expected_status
        or payload.get("result", {}).get("passed") is not True
        or not gates
        or not all(value is True for value in gates.values())
    ):
        raise RuntimeError(f"stage is sealed: {expected_stage} did not pass every gate")
    if payload.get("preregistration_sha256") != prereg_hash:
        raise RuntimeError("stage is sealed: preregistration hash changed")
    if payload.get("source_code_sha256") != _source_hashes():
        raise RuntimeError("stage is sealed: research harness changed")
    return payload


def _decision_digest(result: dict[str, Any], quality: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"result": result, "data_quality": quality},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    result = report["result"]
    primary = result["quarter_hour"]
    lines = [
        f"# H-QH-001 — {report['stage']}",
        "",
        f"- Statut : **{report['status']}**",
        f"- Symbole : **{report['symbol']}**",
        f"- Trades : **{primary['trade_count']}**",
        f"- PnL net à {PRIMARY_COST_BPS:.0f} bps : **{primary['pnl_usd']:.2f} USD**",
        f"- Win rate : **{(primary['win_rate'] or 0) * 100:.2f} %**",
        f"- Borne bootstrap : **{result['bootstrap_lower_95_one_sided']}**",
        f"- p placebo : **{result['matched_placebo']['empirical_p_value']}**",
        f"- Seuil familial : **{FAMILY_ALPHA:.8f}**",
        f"- Test final 2026 scellé : **{str(report['test_final_sealed']).lower()}**",
        "",
        "## Gates",
        "",
    ]
    for name, passed in result["gates"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{name}`")
    lines.extend(
        [
            "",
            "Sortie de recherche uniquement. Aucun ordre paper/live n'est autorisé.",
            "",
        ]
    )
    return "\n".join(lines)


def _artifact_name(stage: str) -> str:
    return {"validation": "validation", "replication": "replication", "final": "final"}[
        stage
    ]


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.refresh and args.cache_only:
        raise ValueError("--refresh and --cache-only are mutually exclusive")
    prereg_hash = sha256_file(PREREGISTRATION_PATH)
    if prereg_hash is None:
        raise RuntimeError(f"missing preregistration: {PREREGISTRATION_PATH}")

    previous: dict[str, Any] = {}
    if args.stage == "validation":
        symbol = PRIMARY_SYMBOL
        segment_start_date = VALIDATION_START
        end_exclusive = VALIDATION_END_EXCLUSIVE
    elif args.stage == "replication":
        previous["validation"] = _assert_artifact(
            args.output_dir / "validation.json",
            expected_stage="validation",
            expected_status="validation_pass",
            prereg_hash=prereg_hash,
        )
        symbol = REPLICATION_SYMBOL
        segment_start_date = VALIDATION_START
        end_exclusive = VALIDATION_END_EXCLUSIVE
    else:
        # These assertions deliberately precede _data_bundle: the holdout cannot
        # be fetched or loaded through this harness until both prior stages pass.
        previous["validation"] = _assert_artifact(
            args.output_dir / "validation.json",
            expected_stage="validation",
            expected_status="validation_pass",
            prereg_hash=prereg_hash,
        )
        previous["replication"] = _assert_artifact(
            args.output_dir / "replication.json",
            expected_stage="replication",
            expected_status="replication_pass",
            prereg_hash=prereg_hash,
        )
        requested_end = date.fromisoformat(args.end_date)
        if requested_end < FINAL_START:
            raise ValueError("--end-date must be within the final 2026 holdout")
        symbol = PRIMARY_SYMBOL
        segment_start_date = FINAL_START
        end_exclusive = requested_end + timedelta(days=1)

    bundle, provenance = _data_bundle(
        cache_dir=args.cache_dir,
        symbol=symbol,
        end_exclusive=end_exclusive,
        refresh=args.refresh,
        cache_only=args.cache_only,
    )
    bars, alignment = align_minute_bars(
        bundle["candles"], bundle["aggressor-differential"]
    )
    segment_start = _unix_start(segment_start_date)
    segment_end = _unix_start(end_exclusive)
    thresholds, threshold_diagnostics = build_causal_weekly_thresholds(
        bars, segment_start=segment_start, segment_end=segment_end
    )
    quality = _quality_report(
        bundle,
        alignment,
        threshold_diagnostics,
        start=segment_start,
        end=segment_end,
    )
    primary_events = generate_events(
        bars,
        thresholds,
        segment_start=segment_start,
        segment_end=segment_end,
        phase_minute=PRIMARY_PHASE_MINUTE,
    )
    placebo_events = generate_events(
        bars,
        thresholds,
        segment_start=segment_start,
        segment_end=segment_end,
        phase_minute=PLACEBO_PHASE_MINUTE,
    )
    primary = build_trade_outcomes(
        primary_events,
        bars,
        segment_start=segment_start,
        segment_end=segment_end,
    )
    placebo = build_trade_outcomes(
        placebo_events,
        bars,
        segment_start=segment_start,
        segment_end=segment_end,
    )
    result = analyze_segment(
        primary,
        placebo,
        segment_start=segment_start,
        segment_end=segment_end,
        data_quality_passed=bool(quality["passed"]),
    )
    if result["passed"]:
        status = {
            "validation": "validation_pass",
            "replication": "replication_pass",
            "final": "exploitable_candidate",
        }[args.stage]
    else:
        status = str(result["status"])
    report = {
        "schema_version": "hqh001-report-v1",
        "stage": args.stage,
        "status": status,
        "symbol": symbol,
        "generated_at": utc_now_iso(),
        "git_commit": safe_git_commit(),
        "data_start": FETCH_START.isoformat(),
        "segment_start": segment_start_date.isoformat(),
        "data_end_exclusive": end_exclusive.isoformat(),
        "resolution": RESOLUTION,
        "preregistration": str(PREREGISTRATION_PATH),
        "preregistration_sha256": prereg_hash,
        "source_code_sha256": _source_hashes(),
        "data_provenance": provenance,
        "data_quality": quality,
        "event_counts": {
            "quarter_hour": len(primary_events),
            "off_quarter_placebo": len(placebo_events),
        },
        "cost_model": {
            "primary_round_trip_bps": PRIMARY_COST_BPS,
            "stress_round_trip_bps": STRESS_COST_BPS,
        },
        "result": result,
        "decision_sha256": _decision_digest(result, quality),
        "previous_artifacts_sha256": {
            name: sha256_file(args.output_dir / f"{name}.json") for name in previous
        },
        "test_final_sealed": args.stage != "final",
        "orders_sent": 0,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    name = _artifact_name(args.stage)
    _atomic_write_json(args.output_dir / f"{name}.json", report)
    (args.output_dir / f"{name}.md").write_text(_markdown(report), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("validation", "replication", "final"), default="validation"
    )
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--end-date",
        default=(datetime.now(tz=UTC).date() - timedelta(days=1)).isoformat(),
        help="inclusive UTC date, used only by --stage final",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run(args)
    except (CollectorError, RuntimeError, ValueError) as exc:
        print(f"H-QH-001 refused: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "stage": report["stage"],
                "status": report["status"],
                "decision_sha256": report["decision_sha256"],
                "test_final_sealed": report["test_final_sealed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
