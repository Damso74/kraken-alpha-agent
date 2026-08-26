"""Run the fail-closed H-WOF-002 cross-sectional validation harness."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.collectors._common import CollectorError, utc_now_iso  # noqa: E402
from src.data.collectors._provenance import safe_git_commit, sha256_file  # noqa: E402
from src.data.collectors.binance_world_order_flow import (  # noqa: E402
    parse_universe_snapshot,
    universe_at,
)
from src.research.world_order_flow import (  # noqa: E402
    analyze_portfolios,
    build_asset_weeks,
    build_portfolio_weeks,
)

PREREGISTRATION_PATH = Path("docs/WORLD_ORDER_FLOW_PREREGISTRATION.md")
FEASIBILITY_PATH = Path("docs/WORLD_ORDER_FLOW_FEASIBILITY.md")
DEFAULT_CACHE_DIR = Path("data/collector_cache/world_order_flow_hwof002")
DEFAULT_OUTPUT_DIR = Path("reports/world_order_flow_hwof002")
VALIDATION_START = date(2024, 1, 1)
FINAL_START = date(2026, 1, 1)
SOURCE_PATHS = (
    Path("scripts/run_world_order_flow_hwof002.py"),
    Path("src/data/collectors/binance_world_order_flow.py"),
    Path("src/research/world_order_flow.py"),
)
BUNDLE_SCHEMA = "hwof002-bundle-v1"


def _unix_start(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(path)


def _source_hashes() -> dict[str, str | None]:
    paths = (*SOURCE_PATHS, PREREGISTRATION_PATH, FEASIBILITY_PATH)
    return {str(path): sha256_file(path) for path in paths}


def _bundle_path(cache_dir: Path, stage: str) -> Path:
    return cache_dir / f"{stage}_bundle.json"


def _load_bundle(path: Path, *, expected_stage: str) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise CollectorError(f"cache-only mode: missing exact bundle {path}")
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CollectorError(f"invalid H-WOF-002 bundle JSON: {path}") from exc
    if not isinstance(bundle, dict) or bundle.get("schema_version") != BUNDLE_SCHEMA:
        raise CollectorError("H-WOF-002 bundle schema mismatch")
    if bundle.get("stage") != expected_stage:
        raise CollectorError("H-WOF-002 bundle stage mismatch")
    for key in (
        "universe_snapshots",
        "kraken_assets_by_week",
        "weekly_flows",
        "weekly_prices",
        "provenance",
    ):
        if not isinstance(bundle.get(key), list):
            raise CollectorError(f"H-WOF-002 bundle missing list: {key}")
    provenance = bundle["provenance"]
    if not provenance:
        raise CollectorError("H-WOF-002 bundle has no provenance")
    for item in provenance:
        if (
            not isinstance(item, dict)
            or not item.get("source")
            or not isinstance(item.get("sha256"), str)
            or len(item["sha256"]) != 64
        ):
            raise CollectorError("H-WOF-002 bundle provenance is incomplete")
    try:
        end_exclusive = date.fromisoformat(str(bundle["data_end_exclusive"]))
    except (KeyError, ValueError) as exc:
        raise CollectorError("H-WOF-002 bundle has invalid data_end_exclusive") from exc
    if expected_stage == "validation":
        if end_exclusive != FINAL_START:
            raise CollectorError("validation bundle must end exactly before 2026")
        cutoff = _unix_start(FINAL_START)
        if any(
            isinstance(row, dict)
            and isinstance(row.get("exit_timestamp"), int)
            and row["exit_timestamp"] >= cutoff
            for row in bundle["weekly_prices"]
        ):
            raise CollectorError("validation bundle contains a 2026 price outcome")
        if any(
            isinstance(row, dict)
            and isinstance(row.get("observed_at"), int)
            and row["observed_at"] >= cutoff
            for row in bundle["universe_snapshots"]
        ):
            raise CollectorError("validation bundle contains a 2026 universe snapshot")
    digest = sha256_file(path)
    if digest is None:
        raise CollectorError("could not hash H-WOF-002 bundle")
    return bundle, digest


def _universe_by_week(bundle: dict[str, Any]) -> tuple[dict[int, list[str]], dict[str, Any]]:
    snapshots = [
        parse_universe_snapshot(raw) for raw in bundle["universe_snapshots"]
    ]
    kraken: dict[int, set[str]] = {}
    for raw in bundle["kraken_assets_by_week"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("week_start"), int):
            raise CollectorError("invalid Kraken point-in-time universe row")
        assets = raw.get("base_assets")
        observed_at = raw.get("observed_at")
        week = int(raw["week_start"])
        if (
            not isinstance(assets, list)
            or not isinstance(observed_at, int)
            or observed_at > week
        ):
            raise CollectorError("non-causal Kraken universe row")
        if week in kraken:
            raise CollectorError("duplicate Kraken universe week")
        kraken[week] = {str(asset).upper() for asset in assets}

    flow_weeks = sorted(
        {
            int(raw["week_start"])
            for raw in bundle["weekly_flows"]
            if isinstance(raw, dict) and isinstance(raw.get("week_start"), int)
        }
    )
    result: dict[int, list[str]] = {}
    missing_kraken = 0
    for week in flow_weeks:
        if week not in kraken:
            missing_kraken += 1
            continue
        binance = {
            member.base_asset
            for member in universe_at(snapshots, decision_timestamp=week)
        }
        result[week] = sorted(binance & kraken[week])
    return result, {
        "flow_weeks": len(flow_weeks),
        "causal_universe_weeks": len(result),
        "missing_kraken_universe_weeks": missing_kraken,
        "minimum_universe_size": min(map(len, result.values()), default=0),
        "maximum_universe_size": max(map(len, result.values()), default=0),
    }


def _segment(
    bundle: dict[str, Any], *, segment_start: int, segment_end: int
) -> dict[str, Any]:
    universe, universe_diagnostics = _universe_by_week(bundle)
    asset_weeks, join_diagnostics = build_asset_weeks(
        bundle["weekly_flows"], bundle["weekly_prices"], universe
    )
    portfolios = [
        row
        for row in build_portfolio_weeks(asset_weeks)
        if segment_start <= row.decision_timestamp and row.exit_timestamp < segment_end
    ]
    analysis = analyze_portfolios(portfolios)
    data_quality = (
        universe_diagnostics["missing_kraken_universe_weeks"] == 0
        and join_diagnostics["invalid_flow_rows"] == 0
        and join_diagnostics["invalid_price_rows"] == 0
        and join_diagnostics["incomplete_weeks_excluded"] == 0
        and universe_diagnostics["minimum_universe_size"] >= 30
    )
    gates = {"causal_complete_data": data_quality, **analysis["gates"]}
    analysis["gates"] = gates
    analysis["status"] = (
        "candidate_for_forward_observation" if all(gates.values()) else "no_go"
    )
    analysis["universe_diagnostics"] = universe_diagnostics
    analysis["join_diagnostics"] = join_diagnostics
    return analysis


def _validation_report_path(output_dir: Path) -> Path:
    return output_dir / "validation.json"


def _assert_final_unlocked(output_dir: Path, hashes: dict[str, str | None]) -> dict[str, Any]:
    path = _validation_report_path(output_dir)
    if not path.is_file():
        raise RuntimeError("final lock: validation report is missing")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "validation_pass":
        raise RuntimeError("final lock: validation did not pass every gate")
    if report.get("source_code_sha256") != hashes:
        raise RuntimeError("final lock: preregistration or source code changed")
    return report


def _markdown(report: dict[str, Any]) -> str:
    validation = report["segments"]["validation"]
    lines = [
        f"# H-WOF-002 — {report['stage']}",
        "",
        f"Statut : **{report['status']}**",
        "",
        "H-WOF-002 est un proxy cross-sectionnel Binance 1d, pas une réplication ",
        "tick-exacte du world order flow multi-places.",
        "",
        "## Validation 2024–2025",
        "",
        f"- Semaines éligibles : {validation['eligible_weeks']}",
        f"- Semaines exposées : {validation['exposed_weeks']}",
        f"- Rendement moyen net : {validation['mean_net_return']}",
        f"- p permutation : {validation['permutation_p_value']}",
        "",
        "## Gates",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        for name, passed in validation["gates"].items()
    )
    lines.extend(
        [
            "",
            "Aucun résultat de ce harnais n'autorise paper trading, live ou ordre.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.cache_only:
        raise ValueError("H-WOF-002 requires explicit --cache-only")
    hashes = _source_hashes()
    if any(value is None for value in hashes.values()):
        raise RuntimeError("missing preregistration, feasibility audit or source file")
    previous: dict[str, Any] | None = None
    if args.stage == "final":
        previous = _assert_final_unlocked(args.output_dir, hashes)
    bundle, bundle_hash = _load_bundle(
        _bundle_path(args.cache_dir, args.stage), expected_stage=args.stage
    )
    validation = _segment(
        bundle,
        segment_start=_unix_start(VALIDATION_START),
        segment_end=_unix_start(FINAL_START),
    )
    status = "validation_pass" if validation["status"].startswith("candidate") else "no_go"
    segments: dict[str, Any] = {"validation": validation}
    sealed = status != "validation_pass"
    if args.stage == "final":
        if previous is None or validation != previous["segments"]["validation"]:
            raise RuntimeError("final lock: historical validation changed")
        final_end = bundle.get("data_end_exclusive")
        if not isinstance(final_end, str):
            raise CollectorError("final bundle has no data_end_exclusive")
        final_segment = _segment(
            bundle,
            segment_start=_unix_start(FINAL_START),
            segment_end=_unix_start(date.fromisoformat(final_end)),
        )
        segments["final"] = final_segment
        status = (
            "candidate_for_forward_observation"
            if final_segment["status"].startswith("candidate")
            else "no_go"
        )
        sealed = False
    report = {
        "schema_version": "hwof002-report-v1",
        "generated_at": utc_now_iso(),
        "stage": args.stage,
        "status": status,
        "nature": "binance_daily_kline_cross_sectional_proxy_not_tick_exact",
        "git_commit": safe_git_commit(),
        "source_code_sha256": hashes,
        "bundle_path": str(_bundle_path(args.cache_dir, args.stage).resolve()),
        "bundle_sha256": bundle_hash,
        "test_final_sealed": sealed,
        "segments": segments,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(args.output_dir / f"{args.stage}.json", report)
    (args.output_dir / f"{args.stage}.md").write_text(
        _markdown(report), encoding="utf-8"
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("validation", "final"), default="validation")
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main() -> int:
    try:
        report = run(_parser().parse_args())
    except (CollectorError, RuntimeError, ValueError) as exc:
        print(f"H-WOF-002 blocked: {exc}", file=sys.stderr)
        return 2
    print(f"H-WOF-002 {report['stage']}: {report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
