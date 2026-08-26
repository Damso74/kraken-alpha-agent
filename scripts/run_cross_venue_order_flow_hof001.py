"""Run preregistered cross-venue weekly order-flow hypothesis H-OF-001."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.collectors._common import CollectorError, utc_now_iso  # noqa: E402
from src.data.collectors._provenance import safe_git_commit, sha256_file  # noqa: E402
from src.data.collectors.binance_public_klines import (  # noqa: E402
    fetch_daily_klines,
)
from src.data.collectors.kraken_futures_charts import (  # noqa: E402
    fetch_analytics,
    fetch_candles,
)
from src.research.cross_venue_order_flow import (  # noqa: E402
    DAY_SECONDS,
    HOUR_SECONDS,
    analyze_segment,
    build_outcomes,
    build_weekly_features,
)

BINANCE_SYMBOL = "BTCUSDT"
KRAKEN_SYMBOL = "PF_XBTUSD"
DATA_START = date(2022, 3, 23)
DEVELOPMENT_START = date(2022, 3, 28)
VALIDATION_START = date(2024, 1, 1)
FINAL_START = date(2026, 1, 1)
VALIDATION_END_EXCLUSIVE = FINAL_START
PREREGISTRATION_PATH = Path("docs/CROSS_VENUE_ORDER_FLOW_PREREGISTRATION.md")
DEFAULT_CACHE_DIR = Path("data/collector_cache/cross_venue_order_flow")
DEFAULT_OUTPUT_DIR = Path("reports/cross_venue_order_flow_hof001")
SOURCE_CODE_PATHS = (
    Path("scripts/run_cross_venue_order_flow_hof001.py"),
    Path("src/data/collectors/binance_public_klines.py"),
    Path("src/data/collectors/kraken_futures_charts.py"),
    Path("src/research/cross_venue_order_flow.py"),
)


def _unix_start(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(path)


def _end_label(end_exclusive: date) -> str:
    return (end_exclusive - timedelta(days=1)).isoformat()


def _cache_path(cache_dir: Path, kind: str, end_exclusive: date) -> Path:
    return cache_dir / (
        f"{kind}_{DATA_START.isoformat()}_{_end_label(end_exclusive)}.json"
    )


def _load_exact_cache(path: Path, expected: dict[str, Any]) -> list[dict[str, Any]]:
    if not path.is_file():
        raise CollectorError(f"cache-only mode: missing exact cache {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key, value in expected.items():
        if payload.get(key) != value:
            raise CollectorError(f"cache metadata mismatch for {path}: {key}")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("row_count") != len(rows):
        raise CollectorError(f"invalid cache rows in {path}")
    return rows


def _fetch_or_load(
    *,
    path: Path,
    expected: dict[str, Any],
    refresh: bool,
    cache_only: bool,
    fetch: Callable[[], list[dict[str, Any]]],
    source_url: str,
) -> tuple[list[dict[str, Any]], str]:
    if path.is_file() and not refresh:
        return _load_exact_cache(path, expected), "cache"
    if cache_only:
        return _load_exact_cache(path, expected), "cache-only"
    rows = fetch()
    _atomic_write_json(
        path,
        {
            "schema_version": "hof001-cache-v1",
            **expected,
            "source_url": source_url,
            "fetched_at": utc_now_iso(),
            "row_count": len(rows),
            "rows": rows,
        },
    )
    return rows, "network"


def _data_bundle(
    *, cache_dir: Path, end_exclusive: date, refresh: bool, cache_only: bool
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    start = _unix_start(DATA_START)
    end = _unix_start(end_exclusive)
    definitions: list[
        tuple[str, dict[str, Any], Callable[[], list[dict[str, Any]]], str]
    ] = [
        (
            "binance_btcusdt_1d",
            {
                "schema_version": "hof001-cache-v1",
                "kind": "binance_klines",
                "symbol": BINANCE_SYMBOL,
                "resolution": "1d",
                "start": start,
                "end_exclusive": end,
            },
            lambda: fetch_daily_klines(start_ms=start * 1000, end_ms=end * 1000),
            "https://data-api.binance.vision/api/v3/klines",
        ),
        (
            "kraken_cvd_1d",
            {
                "schema_version": "hof001-cache-v1",
                "kind": "kraken_cvd",
                "symbol": KRAKEN_SYMBOL,
                "resolution": "1d",
                "start": start,
                "end_exclusive": end,
            },
            lambda: fetch_analytics(
                KRAKEN_SYMBOL,
                "cvd",
                interval_seconds=DAY_SECONDS,
                since=start,
                to=end,
            ),
            (
                "https://futures.kraken.com/api/charts/v1/analytics/"
                f"{KRAKEN_SYMBOL}/cvd"
            ),
        ),
        (
            "kraken_prices_1h",
            {
                "schema_version": "hof001-cache-v1",
                "kind": "kraken_candles",
                "symbol": KRAKEN_SYMBOL,
                "resolution": "1h",
                "start": start,
                "end_exclusive": end,
            },
            lambda: fetch_candles(
                KRAKEN_SYMBOL, "1h", since=start, to=end
            ),
            (
                "https://futures.kraken.com/api/charts/v1/trade/"
                f"{KRAKEN_SYMBOL}/1h"
            ),
        ),
    ]
    bundle: dict[str, list[dict[str, Any]]] = {}
    provenance: dict[str, Any] = {}
    for kind, expected, fetch, source_url in definitions:
        path = _cache_path(cache_dir, kind, end_exclusive)
        rows, mode = _fetch_or_load(
            path=path,
            expected=expected,
            refresh=refresh,
            cache_only=cache_only,
            fetch=fetch,
            source_url=source_url,
        )
        bundle[kind] = rows
        provenance[kind] = {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "row_count": len(rows),
            "load_mode": mode,
        }
    return bundle, provenance


def _coverage(
    rows: list[dict[str, Any]], *, start: int, end: int, step: int
) -> dict[str, Any]:
    expected = set(range(start, end, step))
    timestamps = {
        int(row["timestamp"])
        for row in rows
        if isinstance(row.get("timestamp"), int) and start <= row["timestamp"] < end
    }
    missing = sorted(expected - timestamps)
    off_grid = sorted(timestamps - expected)
    return {
        "expected": len(expected),
        "observed": len(timestamps),
        "coverage": len(timestamps & expected) / len(expected) if expected else 0.0,
        "missing_count": len(missing),
        "off_grid_count": len(off_grid),
        "first_missing": missing[0] if missing else None,
        "first_off_grid": off_grid[0] if off_grid else None,
    }


def _quality_report(
    bundle: dict[str, list[dict[str, Any]]], *, start: int, end: int
) -> dict[str, Any]:
    series = {
        "binance": _coverage(
            bundle["binance_btcusdt_1d"], start=start, end=end, step=DAY_SECONDS
        ),
        "kraken_cvd": _coverage(
            bundle["kraken_cvd_1d"], start=start, end=end, step=DAY_SECONDS
        ),
        "kraken_prices": _coverage(
            bundle["kraken_prices_1h"], start=start, end=end, step=HOUR_SECONDS
        ),
    }
    passed = all(
        float(item["coverage"]) >= 0.95 and int(item["off_grid_count"]) == 0
        for item in series.values()
    )
    return {"passed": passed, **series}


def _source_hashes() -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in SOURCE_CODE_PATHS}


def _validation_path(output_dir: Path) -> Path:
    return output_dir / "validation.json"


def _assert_final_unlocked(output_dir: Path, prereg_hash: str) -> dict[str, Any]:
    path = _validation_path(output_dir)
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
        raise RuntimeError("final stage is sealed: preregistration changed")
    if payload.get("source_code_sha256") != _source_hashes():
        raise RuntimeError("final stage is sealed: research harness changed")
    return payload


def _markdown(report: dict[str, Any]) -> str:
    validation = report["segments"]["validation"]
    primary = validation["primary"]
    lines = [
        "# H-OF-001 — résultat de validation",
        "",
        f"- Statut : **{report['status']}**",
        "- Nature : **proxy inter-places, non-réplication exacte**",
        f"- Semaines exposées : **{primary['trade_count']}**",
        f"- PnL net : **{primary['pnl_usd']:.2f} USD**",
        f"- Win rate : **{(primary['win_rate'] or 0) * 100:.2f} %**",
        f"- Test final 2026 scellé : **{str(report['test_final_sealed']).lower()}**",
        "",
        "## Gates",
        "",
    ]
    for name, passed in validation["gates"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{name}`")
    lines.extend(
        [
            "",
            "Sortie de recherche uniquement : aucun paper trading, live ou ordre",
            "n'est autorisé par ce résultat, qui n'est pas un conseil financier.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(output_dir: Path, name: str, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(output_dir / f"{name}.json", report)
    (output_dir / f"{name}.md").write_text(_markdown(report), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.refresh and args.cache_only:
        raise ValueError("--refresh and --cache-only are mutually exclusive")
    prereg_hash = sha256_file(PREREGISTRATION_PATH)
    if prereg_hash is None:
        raise RuntimeError(f"missing preregistration: {PREREGISTRATION_PATH}")
    previous_validation: dict[str, Any] | None = None
    if args.stage == "validation":
        end_exclusive = VALIDATION_END_EXCLUSIVE
    else:
        previous_validation = _assert_final_unlocked(args.output_dir, prereg_hash)
        requested_end = date.fromisoformat(args.end_date)
        if requested_end < FINAL_START:
            raise ValueError("--end-date must be inside the 2026 final holdout")
        end_exclusive = requested_end + timedelta(days=1)

    bundle, provenance = _data_bundle(
        cache_dir=args.cache_dir,
        end_exclusive=end_exclusive,
        refresh=args.refresh,
        cache_only=args.cache_only,
    )
    features, feature_diagnostics = build_weekly_features(
        bundle["binance_btcusdt_1d"],
        bundle["kraken_cvd_1d"],
        bundle["kraken_prices_1h"],
    )
    development_start = _unix_start(DEVELOPMENT_START)
    validation_start = _unix_start(VALIDATION_START)
    final_start = _unix_start(FINAL_START)
    development_quality = _quality_report(
        bundle, start=development_start, end=validation_start
    )
    validation_quality = _quality_report(
        bundle, start=validation_start, end=final_start
    )
    development_outcomes, development_diagnostics = build_outcomes(
        features,
        bundle["kraken_prices_1h"],
        segment_start=development_start,
        segment_end=validation_start,
    )
    validation_outcomes, validation_diagnostics = build_outcomes(
        features,
        bundle["kraken_prices_1h"],
        segment_start=validation_start,
        segment_end=final_start,
    )
    segments: dict[str, Any] = {
        "development": analyze_segment(
            development_outcomes,
            segment_start=development_start,
            segment_end=validation_start,
            required_years=(2023,),
            data_quality_passed=bool(development_quality["passed"]),
        ),
        "validation": analyze_segment(
            validation_outcomes,
            segment_start=validation_start,
            segment_end=final_start,
            required_years=(2024, 2025),
            data_quality_passed=bool(validation_quality["passed"]),
        ),
    }
    validation_passed = bool(segments["validation"]["passed"])
    status = (
        "validation_pass"
        if validation_passed
        else segments["validation"]["status"]
    )
    sealed = not validation_passed
    quality: dict[str, Any] = {
        "development": development_quality,
        "validation": validation_quality,
    }
    outcome_diagnostics: dict[str, Any] = {
        "development": development_diagnostics,
        "validation": validation_diagnostics,
    }

    if args.stage == "final":
        if segments["validation"] != previous_validation["segments"]["validation"]:
            raise RuntimeError(
                "final stage is sealed: validation metrics changed after source refresh"
            )
        final_end = _unix_start(end_exclusive)
        final_quality = _quality_report(bundle, start=final_start, end=final_end)
        final_outcomes, final_diagnostics = build_outcomes(
            features,
            bundle["kraken_prices_1h"],
            segment_start=final_start,
            segment_end=final_end,
        )
        segments["final"] = analyze_segment(
            final_outcomes,
            segment_start=final_start,
            segment_end=final_end,
            required_years=(2026,),
            data_quality_passed=bool(final_quality["passed"]),
        )
        both_pass = validation_passed and bool(segments["final"]["passed"])
        status = (
            "candidate_for_forward_observation"
            if both_pass
            else segments["final"]["status"]
        )
        sealed = False
        quality["final"] = final_quality
        outcome_diagnostics["final"] = final_diagnostics

    report = {
        "schema_version": "hof001-report-v1",
        "generated_at": utc_now_iso(),
        "stage": args.stage,
        "status": status,
        "nature": "cross_venue_order_flow_proxy_not_exact_replication",
        "symbol": KRAKEN_SYMBOL,
        "preregistration": str(PREREGISTRATION_PATH),
        "preregistration_sha256": prereg_hash,
        "git_commit": safe_git_commit(),
        "source_code_sha256": _source_hashes(),
        "data_end_exclusive": end_exclusive.isoformat(),
        "test_final_sealed": sealed,
        "previous_validation_sha256": (
            sha256_file(_validation_path(args.output_dir))
            if previous_validation is not None
            else None
        ),
        "cost_model": {
            "primary_round_trip_bps_per_exposed_week": 50,
            "stress_round_trip_bps_per_exposed_week": 100,
            "note": "conservative discrete weekly turnover model",
        },
        "source_docs": {
            "binance": (
                "https://github.com/binance/binance-spot-api-docs/blob/master/"
                "rest-api.md"
            ),
            "kraken_analytics": (
                "https://docs.kraken.com/api/docs/futures-api/charts/"
                "market-analytics"
            ),
            "primary_paper": "https://doi.org/10.1016/j.finmar.2026.101047",
        },
        "data_provenance": provenance,
        "data_quality": quality,
        "feature_diagnostics": feature_diagnostics,
        "outcome_diagnostics": outcome_diagnostics,
        "segments": segments,
    }
    _write_report(args.output_dir, args.stage, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("validation", "final"), default="validation")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--end-date", default=(date.today() - timedelta(days=1)).isoformat()
    )
    return parser


def main() -> int:
    try:
        report = run(_parser().parse_args())
    except (CollectorError, RuntimeError, ValueError) as exc:
        print(f"H-OF-001 blocked: {exc}", file=sys.stderr)
        return 2
    validation = report["segments"]["validation"]["primary"]
    print(
        f"H-OF-001 {report['stage']}: {report['status']} | "
        f"validation weeks={validation['trade_count']} "
        f"pnl_usd={validation['pnl_usd']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
