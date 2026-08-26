"""Run preregistered exploratory DVOL proxy hypothesis H-DV-001."""

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
from src.data.collectors.deribit_dvol import fetch_dvol_candles  # noqa: E402
from src.data.collectors.kraken_futures_charts import fetch_candles  # noqa: E402
from src.research.deribit_dvol import (  # noqa: E402
    DAY_SECONDS,
    HOUR_SECONDS,
    analyze_segment,
    build_daily_features,
    build_outcomes,
)

CURRENCY = "BTC"
SYMBOL = "PF_XBTUSD"
DVOL_RESOLUTION = "1D"
PRICE_RESOLUTION = "1h"
DVOL_START = date(2021, 3, 24)
PRICE_START = date(2022, 3, 23)
DEVELOPMENT_START = date(2022, 3, 24)
VALIDATION_START = date(2024, 1, 1)
FINAL_START = date(2026, 1, 1)
VALIDATION_END_EXCLUSIVE = FINAL_START
PREREGISTRATION_PATH = Path("docs/DERIBIT_DVOL_PREREGISTRATION.md")
DEFAULT_CACHE_DIR = Path("data/collector_cache/deribit_dvol")
DEFAULT_OUTPUT_DIR = Path("reports/deribit_dvol_hdv001")
SOURCE_CODE_PATHS = (
    Path("scripts/run_deribit_dvol_hdv001.py"),
    Path("src/data/collectors/deribit_dvol.py"),
    Path("src/data/collectors/kraken_futures_charts.py"),
    Path("src/research/deribit_dvol.py"),
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


def _date_label(end_exclusive: date) -> str:
    return (end_exclusive - timedelta(days=1)).isoformat()


def _dvol_cache_path(cache_dir: Path, end_exclusive: date) -> Path:
    return cache_dir / (
        f"{CURRENCY}_{DVOL_RESOLUTION}_{DVOL_START.isoformat()}_"
        f"{_date_label(end_exclusive)}.json"
    )


def _price_cache_path(cache_dir: Path, end_exclusive: date) -> Path:
    return cache_dir / (
        f"{SYMBOL}_{PRICE_RESOLUTION}_{PRICE_START.isoformat()}_"
        f"{_date_label(end_exclusive)}.json"
    )


def _load_exact_cache(
    path: Path,
    *,
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
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
        return _load_exact_cache(path, expected=expected), "cache"
    if cache_only:
        return _load_exact_cache(path, expected=expected), "cache-only"
    rows = fetch()
    payload = {
        "schema_version": "hdv001-cache-v1",
        **expected,
        "source_url": source_url,
        "fetched_at": utc_now_iso(),
        "row_count": len(rows),
        "rows": rows,
    }
    _atomic_write_json(path, payload)
    return rows, "network"


def _data_bundle(
    *, cache_dir: Path, end_exclusive: date, refresh: bool, cache_only: bool
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    dvol_start = _unix_start(DVOL_START)
    price_start = _unix_start(PRICE_START)
    end = _unix_start(end_exclusive)
    dvol_path = _dvol_cache_path(cache_dir, end_exclusive)
    price_path = _price_cache_path(cache_dir, end_exclusive)
    dvol_expected = {
        "schema_version": "hdv001-cache-v1",
        "kind": "deribit_dvol",
        "currency": CURRENCY,
        "resolution": DVOL_RESOLUTION,
        "start": dvol_start,
        "end_exclusive": end,
    }
    price_expected = {
        "schema_version": "hdv001-cache-v1",
        "kind": "kraken_candles",
        "symbol": SYMBOL,
        "resolution": PRICE_RESOLUTION,
        "start": price_start,
        "end_exclusive": end,
    }
    dvol_rows, dvol_mode = _fetch_or_load(
        path=dvol_path,
        expected=dvol_expected,
        refresh=refresh,
        cache_only=cache_only,
        fetch=lambda: fetch_dvol_candles(
            CURRENCY,
            start_timestamp_ms=dvol_start * 1000,
            end_timestamp_ms=end * 1000,
            resolution=DVOL_RESOLUTION,
        ),
        source_url=(
            "https://www.deribit.com/api/v2/public/get_volatility_index_data"
        ),
    )
    price_rows, price_mode = _fetch_or_load(
        path=price_path,
        expected=price_expected,
        refresh=refresh,
        cache_only=cache_only,
        fetch=lambda: fetch_candles(
            SYMBOL, PRICE_RESOLUTION, since=price_start, to=end
        ),
        source_url=(
            f"https://futures.kraken.com/api/charts/v1/trade/{SYMBOL}/"
            f"{PRICE_RESOLUTION}"
        ),
    )
    bundle = {"dvol": dvol_rows, "prices": price_rows}
    provenance = {
        "dvol": {
            "path": str(dvol_path.resolve()),
            "sha256": sha256_file(dvol_path),
            "row_count": len(dvol_rows),
            "load_mode": dvol_mode,
        },
        "prices": {
            "path": str(price_path.resolve()),
            "sha256": sha256_file(price_path),
            "row_count": len(price_rows),
            "load_mode": price_mode,
        },
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
    dvol = _coverage(bundle["dvol"], start=start, end=end, step=DAY_SECONDS)
    prices = _coverage(bundle["prices"], start=start, end=end, step=HOUR_SECONDS)
    passed = (
        float(dvol["coverage"]) >= 0.95
        and float(prices["coverage"]) >= 0.95
        and int(dvol["off_grid_count"]) == 0
        and int(prices["off_grid_count"]) == 0
    )
    return {"passed": passed, "dvol": dvol, "prices": prices}


def _source_hashes() -> dict[str, str | None]:
    return {str(path): sha256_file(path) for path in SOURCE_CODE_PATHS}


def _validation_path(output_dir: Path) -> Path:
    return output_dir / "validation.json"


def _assert_final_unlocked(
    output_dir: Path, preregistration_hash: str
) -> dict[str, Any]:
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
    if payload.get("preregistration_sha256") != preregistration_hash:
        raise RuntimeError("final stage is sealed: preregistration changed")
    if payload.get("source_code_sha256") != _source_hashes():
        raise RuntimeError("final stage is sealed: research harness changed")
    return payload


def _markdown(report: dict[str, Any]) -> str:
    validation = report["segments"]["validation"]
    primary = validation["primary"]
    lines = [
        "# H-DV-001 — résultat de validation",
        "",
        f"- Statut : **{report['status']}**",
        "- Nature : **proxy DVOL exploratoire, non-réplication**",
        f"- Trades validation : **{primary['trade_count']}**",
        f"- PnL net validation : **{primary['pnl_usd']:.2f} USD**",
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
            "Ce rapport est une sortie de recherche. Il n'autorise ni paper trading,",
            "ni live, ni ordre et ne constitue pas un conseil financier.",
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
    preregistration_hash = sha256_file(PREREGISTRATION_PATH)
    if preregistration_hash is None:
        raise RuntimeError(f"missing preregistration: {PREREGISTRATION_PATH}")
    previous_validation: dict[str, Any] | None = None
    if args.stage == "validation":
        end_exclusive = VALIDATION_END_EXCLUSIVE
    else:
        previous_validation = _assert_final_unlocked(
            args.output_dir, preregistration_hash
        )
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
    features, feature_diagnostics = build_daily_features(
        bundle["dvol"], bundle["prices"]
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
    development_signals, development_placebo, development_diagnostics = (
        build_outcomes(
            features,
            bundle["prices"],
            segment_start=development_start,
            segment_end=validation_start,
        )
    )
    validation_signals, validation_placebo, validation_diagnostics = build_outcomes(
        features,
        bundle["prices"],
        segment_start=validation_start,
        segment_end=final_start,
    )
    segments: dict[str, Any] = {
        "development": analyze_segment(
            development_signals,
            development_placebo,
            segment_start=development_start,
            segment_end=validation_start,
            required_years=(2022, 2023),
            data_quality_passed=bool(development_quality["passed"]),
        ),
        "validation": analyze_segment(
            validation_signals,
            validation_placebo,
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
    test_final_sealed = not validation_passed
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
        final_signals, final_placebo, final_diagnostics = build_outcomes(
            features,
            bundle["prices"],
            segment_start=final_start,
            segment_end=final_end,
        )
        segments["final"] = analyze_segment(
            final_signals,
            final_placebo,
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
        test_final_sealed = False
        quality["final"] = final_quality
        outcome_diagnostics["final"] = final_diagnostics

    report = {
        "schema_version": "hdv001-report-v1",
        "generated_at": utc_now_iso(),
        "stage": args.stage,
        "status": status,
        "nature": "exploratory_dvol_proxy_not_replication",
        "symbol": SYMBOL,
        "preregistration": str(PREREGISTRATION_PATH),
        "preregistration_sha256": preregistration_hash,
        "git_commit": safe_git_commit(),
        "source_code_sha256": _source_hashes(),
        "data_end_exclusive": end_exclusive.isoformat(),
        "test_final_sealed": test_final_sealed,
        "previous_validation_sha256": (
            sha256_file(_validation_path(args.output_dir))
            if previous_validation is not None
            else None
        ),
        "cost_model": {
            "primary_round_trip_bps": 50,
            "taker_fee_round_trip_bps": 10,
            "slippage_round_trip_bps": 20,
            "funding_buffer_bps": 20,
            "stress_round_trip_bps": 100,
        },
        "source_docs": {
            "dvol": (
                "https://docs.deribit.com/api-reference/market-data/"
                "public-get_volatility_index_data"
            ),
            "kraken_candles": (
                "https://docs.kraken.com/api/docs/futures-api/charts/candles"
            ),
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
        print(f"H-DV-001 blocked: {exc}", file=sys.stderr)
        return 2
    validation = report["segments"]["validation"]["primary"]
    print(
        f"H-DV-001 {report['stage']}: {report['status']} | "
        f"validation trades={validation['trade_count']} "
        f"pnl_usd={validation['pnl_usd']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
