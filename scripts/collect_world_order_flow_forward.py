"""Operate the forward-only, no-order H-WOF-002 data journal.

The scheduled workflow is intentionally two days causal at bootstrap:

1. capture today's public ``exchangeInfo`` snapshot;
2. collect yesterday's fully closed 1d klines using the latest snapshot that
   already existed before the start of that day's UTC week;
3. append one immutable daily artifact and its SHA-256 manifest record;
4. once a source week's seven-day outcome is closed, capture the exact Kraken
   1h opens required by the frozen execution rule in a separate immutable
   weekly artifact.

No future price is read before it exists. No position, paper fill, live order
or credential is read or created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time as time_module
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.collectors._common import (  # noqa: E402
    CollectorError,
    HttpFetcherFn,
    default_http_fetcher,
)
from src.data.collectors._provenance import sha256_file  # noqa: E402
from src.data.collectors.binance_world_order_flow import (  # noqa: E402
    DAILY_KLINES_URL,
    UniverseSnapshot,
    append_universe_snapshot,
    fetch_daily_klines,
    fetch_exchange_info_snapshot,
    load_universe_snapshots,
    parse_universe_snapshot,
    universe_at,
)
from src.research.world_order_flow import (  # noqa: E402
    ENTRY_DELAY_SECONDS,
    WEEK_SECONDS,
)

FORWARD_SCHEMA = "hwof002-forward-day-v1"
MANIFEST_SCHEMA = "hwof002-forward-manifest-v1"
UNIVERSE_SCHEMA = "hwof002-forward-kraken-universe-v1"
KRAKEN_ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"
KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_UNIVERSE_MANIFEST_SCHEMA = "hwof002-kraken-universe-manifest-v1"
WEEK_OUTCOME_SCHEMA = "hwof002-forward-week-outcome-v1"
WEEK_OUTCOME_MANIFEST_SCHEMA = "hwof002-forward-week-outcome-manifest-v1"
DEFAULT_ROOT = Path("data/collector_cache/world_order_flow_forward")
DEFAULT_MIN_ASSETS = 30
DEFAULT_MAX_ASSETS = 80
KRAKEN_PUBLIC_REQUEST_INTERVAL_SECONDS = 1.05
KRAKEN_QUOTE_PRIORITY = {"USD": 0, "USDT": 1, "USDC": 2}
NON_CRYPTO_BASE_ASSETS = {
    "USD",
    "USDT",
    "USDC",
    "EUR",
    "EURT",
    "GBP",
    "CAD",
    "CHF",
    "AUD",
    "JPY",
    "DAI",
    "PYUSD",
}
KRAKEN_BASE_ALIASES = {"XBT": "BTC", "XDG": "DOGE"}
REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN_SOURCE_PATHS = {
    "preregistration_sha256": REPO_ROOT / "docs/WORLD_ORDER_FLOW_PREREGISTRATION.md",
    "analysis_sha256": REPO_ROOT / "src/research/world_order_flow.py",
    "collector_sha256": Path(__file__).resolve(),
    "evaluator_sha256": REPO_ROOT / "scripts/evaluate_world_order_flow_forward.py",
    "ci_attestation_sha256": REPO_ROOT / "src/research/ci_attestation.py",
}


def _current_source_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for label, path in FROZEN_SOURCE_PATHS.items():
        digest = sha256_file(path)
        if digest is None:
            raise CollectorError(f"could not hash frozen H-WOF source: {path}")
        hashes[label] = digest
    return hashes


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _unix_day_start(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp())


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _snapshot_log(root: Path) -> Path:
    return root / "universe_snapshots.jsonl"


def _snapshot_day_path(root: Path, value: date) -> Path:
    return root / "snapshot_days" / f"{value.isoformat()}.json"


def _forward_day_path(root: Path, value: date) -> Path:
    return root / "days" / f"{value.isoformat()}.json"


def _manifest_path(root: Path) -> Path:
    return root / "manifest.jsonl"


def _kraken_snapshot_day_path(root: Path, value: date) -> Path:
    return root / "kraken_universe_days" / f"{value.isoformat()}.json"


def _kraken_universe_manifest_path(root: Path) -> Path:
    return root / "kraken_universe_manifest.jsonl"


def _week_outcome_path(root: Path, week_start: date) -> Path:
    return root / "week_outcomes" / f"{week_start.isoformat()}.json"


def _week_outcome_manifest_path(root: Path) -> Path:
    return root / "week_outcome_manifest.jsonl"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorError(f"invalid JSON file: {path}") from exc


def _capture_snapshot(
    root: Path,
    *,
    now: datetime,
    fetcher: HttpFetcherFn,
) -> tuple[UniverseSnapshot, str, bool]:
    """Capture at most one immutable snapshot per UTC date."""

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    normalized = now.astimezone(UTC)
    path = _snapshot_day_path(root, normalized.date())
    created = False
    if path.is_file():
        snapshot = parse_universe_snapshot(_load_json(path))
    else:
        snapshot = fetch_exchange_info_snapshot(fetcher=fetcher, observed_at=normalized)
        _atomic_write_json(path, snapshot.to_dict())
        created = True
    digest = sha256_file(path)
    if digest is None:
        raise CollectorError("could not hash captured universe snapshot")

    log_path = _snapshot_log(root)
    if log_path.is_file():
        existing = load_universe_snapshots(log_path)
        matches = [row for row in existing if row.observed_at == snapshot.observed_at]
        if matches:
            if matches != [snapshot]:
                raise CollectorError("snapshot day conflicts with append-only log")
        else:
            append_universe_snapshot(log_path, snapshot)
    else:
        append_universe_snapshot(log_path, snapshot)
    return snapshot, digest, created


def parse_kraken_asset_pairs(
    payload: Any,
    *,
    observed_at: datetime,
    minimum_assets: int,
    maximum_assets: int,
) -> dict[str, Any]:
    """Normalize public spot pairs into a deterministic 30-80 asset universe."""

    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    if not 0 < minimum_assets <= maximum_assets:
        raise ValueError("invalid Kraken universe bounds")
    if not isinstance(payload, Mapping):
        raise CollectorError("Kraken AssetPairs payload is not an object")
    errors = payload.get("error")
    result = payload.get("result")
    if errors not in ([], None) or not isinstance(result, Mapping):
        raise CollectorError(f"Kraken AssetPairs returned errors: {errors!r}")

    by_base: dict[str, dict[str, Any]] = {}
    for pair_key, raw in result.items():
        if not isinstance(raw, Mapping):
            raise CollectorError("Kraken AssetPairs row is not an object")
        base_raw = str(raw.get("base", ""))
        base = KRAKEN_BASE_ALIASES.get(base_raw.upper(), base_raw.upper())
        quote = str(raw.get("quote", "")).upper()
        status = str(raw.get("status", "")).lower()
        wsname = str(raw.get("wsname", ""))
        if (
            raw.get("aclass_base") != "currency"
            or raw.get("aclass_quote") != "currency"
            or raw.get("lot") != "unit"
            or status != "online"
            or quote not in KRAKEN_QUOTE_PRIORITY
            or not base.isalnum()
            or base in NON_CRYPTO_BASE_ASSETS
            or base_raw.endswith("x")
            or ".x/" in wsname
        ):
            continue
        candidate = {
            "base_asset": base,
            "quote_asset": quote,
            "pair": str(pair_key),
            "altname": str(raw.get("altname", "")),
            "wsname": wsname,
            "status": status,
            "mode": "spot_long_only",
        }
        previous = by_base.get(base)
        if previous is None or (KRAKEN_QUOTE_PRIORITY[quote], candidate["pair"]) < (
            KRAKEN_QUOTE_PRIORITY[str(previous["quote_asset"])],
            str(previous["pair"]),
        ):
            by_base[base] = candidate

    selected = [by_base[base] for base in sorted(by_base)[:maximum_assets]]
    if len(selected) < minimum_assets:
        raise CollectorError(
            f"Kraken public universe has {len(selected)} eligible assets; "
            f"need at least {minimum_assets}"
        )
    normalized = observed_at.astimezone(UTC)
    return {
        "schema_version": UNIVERSE_SCHEMA,
        "observed_at": int(normalized.timestamp()),
        "observed_at_iso": normalized.isoformat().replace("+00:00", "Z"),
        "source": KRAKEN_ASSET_PAIRS_URL,
        "source_params": {"assetVersion": 1},
        "selection": {
            "quotes_by_priority": ["USD", "USDT", "USDC"],
            "status": "online",
            "asset_class": "currency",
            "lot": "unit",
            "mode": "spot_long_only",
            "overflow_rule": "lexicographically_first_base_assets",
            "minimum_assets": minimum_assets,
            "maximum_assets": maximum_assets,
        },
        "base_assets": [row["base_asset"] for row in selected],
        "pairs": selected,
    }


def _capture_kraken_snapshot(
    root: Path,
    *,
    now: datetime,
    fetcher: HttpFetcherFn,
    minimum_assets: int,
    maximum_assets: int,
) -> tuple[dict[str, Any], str, bool]:
    """Capture one immutable, public Kraken AssetPairs universe per UTC day."""

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    normalized = now.astimezone(UTC)
    path = _kraken_snapshot_day_path(root, normalized.date())
    created = False
    if path.is_file():
        raw = _load_json(path)
        if not isinstance(raw, dict) or raw.get("schema_version") != UNIVERSE_SCHEMA:
            raise CollectorError("invalid cached Kraken universe snapshot")
    else:
        payload = fetcher(KRAKEN_ASSET_PAIRS_URL, {"assetVersion": 1})
        raw = parse_kraken_asset_pairs(
            payload,
            observed_at=normalized,
            minimum_assets=minimum_assets,
            maximum_assets=maximum_assets,
        )
        _atomic_write_json(path, raw)
        created = True
    digest = sha256_file(path)
    if digest is None:
        raise CollectorError("could not hash Kraken universe snapshot")
    record = {
        "schema_version": KRAKEN_UNIVERSE_MANIFEST_SCHEMA,
        "day": normalized.date().isoformat(),
        "observed_at": raw["observed_at"],
        "path": str(Path("kraken_universe_days") / path.name),
        "sha256": digest,
        "asset_count": len(raw["base_assets"]),
        "source": KRAKEN_ASSET_PAIRS_URL,
    }
    _append_typed_manifest(
        _kraken_universe_manifest_path(root),
        record,
        schema=KRAKEN_UNIVERSE_MANIFEST_SCHEMA,
    )
    return raw, digest, created


def _load_typed_manifest(path: Path, *, schema: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CollectorError(f"invalid manifest JSON at line {line_number}") from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != schema:
            raise CollectorError(f"invalid manifest record at line {line_number}")
        day = str(raw.get("day", ""))
        if day in seen:
            raise CollectorError(f"duplicate manifest day: {day}")
        seen.add(day)
        records.append(raw)
    if records != sorted(records, key=lambda row: str(row["day"])):
        raise CollectorError("manifest is not chronological")
    return records


def _append_typed_manifest(path: Path, record: dict[str, Any], *, schema: str) -> bool:
    existing = _load_typed_manifest(path, schema=schema)
    same_day = [row for row in existing if row["day"] == record["day"]]
    if same_day:
        if same_day != [record]:
            raise CollectorError(f"immutable manifest conflict for {record['day']}")
        return False
    if existing and str(record["day"]) <= str(existing[-1]["day"]):
        raise CollectorError("manifest backfill would violate append-only ordering")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return True


def _latest_causal_kraken_snapshot(root: Path, *, target_day: date) -> tuple[dict[str, Any], str]:
    known_by = _unix_day_start(_week_start(target_day))
    records = _load_typed_manifest(
        _kraken_universe_manifest_path(root),
        schema=KRAKEN_UNIVERSE_MANIFEST_SCHEMA,
    )
    eligible = [row for row in records if int(row["observed_at"]) <= known_by]
    if not eligible:
        raise CollectorError("bootstrap incomplete: no Kraken universe predates target week")
    record = max(eligible, key=lambda row: int(row["observed_at"]))
    expected = Path("kraken_universe_days") / f"{record['day']}.json"
    if Path(str(record["path"])) != expected:
        raise CollectorError("Kraken universe manifest path is not canonical")
    path = root / expected
    raw = _load_json(path)
    digest = sha256_file(path)
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != UNIVERSE_SCHEMA
        or digest != record.get("sha256")
        or len(raw.get("base_assets", [])) != record.get("asset_count")
    ):
        raise CollectorError("Kraken universe snapshot/manifest mismatch")
    return raw, str(digest)


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CollectorError(f"invalid manifest JSON at line {line_number}") from exc
        if not isinstance(raw, dict) or raw.get("schema_version") != MANIFEST_SCHEMA:
            raise CollectorError(f"invalid manifest record at line {line_number}")
        day = str(raw.get("day", ""))
        if day in seen:
            raise CollectorError(f"duplicate manifest day: {day}")
        seen.add(day)
        records.append(raw)
    ordered = sorted(records, key=lambda row: str(row["day"]))
    if records != ordered:
        raise CollectorError("forward manifest is not chronological")
    return records


def _append_manifest(path: Path, record: dict[str, Any]) -> bool:
    existing = _load_manifest(path)
    same_day = [row for row in existing if row["day"] == record["day"]]
    if same_day:
        if same_day != [record]:
            raise CollectorError(f"immutable manifest conflict for {record['day']}")
        return False
    if existing and str(record["day"]) <= str(existing[-1]["day"]):
        raise CollectorError("manifest backfill would violate append-only ordering")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return True


def _latest_causal_snapshot(root: Path, *, target_day: date) -> tuple[UniverseSnapshot, str]:
    log_path = _snapshot_log(root)
    snapshots = load_universe_snapshots(log_path)
    known_by = _unix_day_start(_week_start(target_day))
    snapshot = max(
        (row for row in snapshots if row.observed_at <= known_by),
        key=lambda row: row.observed_at,
        default=None,
    )
    if snapshot is None:
        raise CollectorError("bootstrap incomplete: no universe snapshot predates target week")
    day_path = _snapshot_day_path(root, datetime.fromtimestamp(snapshot.observed_at, tz=UTC).date())
    digest = sha256_file(day_path)
    if digest is None or parse_universe_snapshot(_load_json(day_path)) != snapshot:
        raise CollectorError("causal snapshot file/log mismatch")
    return snapshot, digest


def _verify_day_file(path: Path, *, expected_day: date) -> tuple[dict[str, Any], str]:
    raw = _load_json(path)
    if not isinstance(raw, dict) or raw.get("schema_version") != FORWARD_SCHEMA:
        raise CollectorError(f"invalid forward day schema: {path}")
    if raw.get("day") != expected_day.isoformat():
        raise CollectorError(f"forward day identity mismatch: {path}")
    rows = raw.get("rows")
    if not isinstance(rows, list) or raw.get("row_count") != len(rows):
        raise CollectorError(f"invalid forward day rows: {path}")
    source_hashes = raw.get("source_hashes")
    if (
        not isinstance(source_hashes, dict)
        or set(source_hashes) != set(FROZEN_SOURCE_PATHS)
        or any(not isinstance(value, str) or len(value) != 64 for value in source_hashes.values())
    ):
        raise CollectorError(f"invalid frozen source hashes in forward day: {path}")
    prohibited = {"return", "returns", "exit_price", "outcome", "pnl", "position"}
    if prohibited & set(raw):
        raise CollectorError(f"forward day contains prohibited outcome fields: {path}")
    day_start = _unix_day_start(expected_day)
    assets: set[str] = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("timestamp") != day_start
            or not isinstance(row.get("base_asset"), str)
            or bool(prohibited & set(row))
        ):
            raise CollectorError(f"forward day contains a non-closed candle: {path}")
        asset = str(row["base_asset"])
        if asset in assets:
            raise CollectorError(f"duplicate asset in forward day: {asset}")
        assets.add(asset)
    digest = sha256_file(path)
    if digest is None:
        raise CollectorError(f"could not hash forward day: {path}")
    return raw, digest


def _kraken_open_from_payload(payload: Any, *, pair: str, expected_timestamp: int) -> float:
    """Return one exact, closed 1h Kraken open or fail closed.

    Kraken canonicalises pair names in the response, so the requested key is
    only a hint.  Selecting by the frozen timestamp avoids accepting the most
    recent candle or silently shifting the execution time.
    """

    if not isinstance(payload, Mapping):
        raise CollectorError(f"Kraken OHLC payload is not an object for {pair}")
    errors = payload.get("error")
    result = payload.get("result")
    if errors not in ([], None) or not isinstance(result, Mapping):
        raise CollectorError(f"Kraken OHLC returned errors for {pair}: {errors!r}")
    matches: list[float] = []
    for key, raw_rows in result.items():
        if key == "last" or not isinstance(raw_rows, list):
            continue
        for raw in raw_rows:
            if not isinstance(raw, list) or len(raw) < 2:
                continue
            try:
                timestamp = int(raw[0])
                open_price = float(raw[1])
            except (TypeError, ValueError):
                continue
            if timestamp == expected_timestamp and open_price > 0:
                matches.append(open_price)
    if len(matches) != 1:
        raise CollectorError(
            f"Kraken OHLC exact open missing or duplicated for {pair} at {expected_timestamp}"
        )
    return matches[0]


def _verify_week_outcome_file(
    path: Path, *, expected_week_start: date
) -> tuple[dict[str, Any], str]:
    raw = _load_json(path)
    if not isinstance(raw, dict) or raw.get("schema_version") != WEEK_OUTCOME_SCHEMA:
        raise CollectorError(f"invalid forward week outcome schema: {path}")
    if raw.get("source_week_start") != expected_week_start.isoformat():
        raise CollectorError(f"forward week outcome identity mismatch: {path}")
    status = raw.get("status")
    rows = raw.get("rows")
    if status not in {"complete", "excluded_incomplete_source_week"}:
        raise CollectorError(f"invalid forward week outcome status: {path}")
    if not isinstance(rows, list) or raw.get("row_count") != len(rows):
        raise CollectorError(f"invalid forward week outcome rows: {path}")
    source_hashes = raw.get("source_hashes")
    if (
        not isinstance(source_hashes, dict)
        or set(source_hashes) != set(FROZEN_SOURCE_PATHS)
        or any(not isinstance(value, str) or len(value) != 64 for value in source_hashes.values())
    ):
        raise CollectorError(f"invalid frozen source hashes in week outcome: {path}")
    week_timestamp = _unix_day_start(expected_week_start)
    entry_timestamp = week_timestamp + WEEK_SECONDS + ENTRY_DELAY_SECONDS
    exit_timestamp = entry_timestamp + WEEK_SECONDS
    assets: set[str] = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("week_start") != week_timestamp
            or row.get("entry_timestamp") != entry_timestamp
            or row.get("exit_timestamp") != exit_timestamp
            or not isinstance(row.get("base_asset"), str)
        ):
            raise CollectorError(f"invalid row in forward week outcome: {path}")
        asset = str(row["base_asset"])
        if asset in assets:
            raise CollectorError(f"duplicate asset in forward week outcome: {asset}")
        assets.add(asset)
        for field in (
            "quote_volume",
            "taker_buy_quote_volume",
            "entry_price",
            "exit_price",
        ):
            try:
                value = float(row[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise CollectorError(f"invalid {field} in forward week outcome: {path}") from exc
            if value <= 0 and field != "taker_buy_quote_volume":
                raise CollectorError(f"non-positive {field} in forward week outcome: {path}")
            if field == "taker_buy_quote_volume" and value < 0:
                raise CollectorError(f"negative {field} in forward week outcome: {path}")
        if float(row["taker_buy_quote_volume"]) > float(row["quote_volume"]):
            raise CollectorError(f"buy volume exceeds total in forward week: {path}")
    if status == "complete" and not rows:
        raise CollectorError(f"complete forward week outcome has no rows: {path}")
    if status != "complete" and rows:
        raise CollectorError(f"excluded forward week outcome contains rows: {path}")
    digest = sha256_file(path)
    if digest is None:
        raise CollectorError(f"could not hash forward week outcome: {path}")
    return raw, digest


def _source_week_candidates(records: list[dict[str, Any]], *, today: date) -> list[date]:
    """Return chronologically mature source weeks represented in the journal.

    The scheduled job runs shortly after UTC midnight.  Requiring the Tuesday
    after the exit Monday gives Kraken's 01:00 UTC exit candle ample time to
    close before it can enter an immutable outcome artifact.
    """

    if not records:
        return []
    first_day = date.fromisoformat(str(records[0]["day"]))
    first_week = _week_start(first_day)
    latest_mature_week = _week_start(today - timedelta(days=15))
    if latest_mature_week < first_week:
        return []
    count = (latest_mature_week - first_week).days // 7
    return [first_week + timedelta(days=7 * index) for index in range(count + 1)]


def collect_mature_week_outcome(
    *,
    root: Path,
    now: datetime,
    fetcher: HttpFetcherFn = default_http_fetcher,
    request_interval_seconds: float = KRAKEN_PUBLIC_REQUEST_INTERVAL_SECONDS,
    sleeper: Callable[[float], None] = time_module.sleep,
) -> dict[str, Any]:
    """Finalize the earliest mature H-WOF source week, at most once.

    Missing daily source data is recorded as an immutable exclusion.  A
    transport error or a missing exact Kraken candle writes nothing and is
    retried by the next scheduled run.
    """

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if request_interval_seconds < 0:
        raise ValueError("request_interval_seconds must be non-negative")
    normalized = now.astimezone(UTC)
    records = _load_manifest(_manifest_path(root))
    outcome_records = _load_typed_manifest(
        _week_outcome_manifest_path(root), schema=WEEK_OUTCOME_MANIFEST_SCHEMA
    )
    completed = {date.fromisoformat(str(row["day"])) for row in outcome_records}
    pending = [
        week
        for week in _source_week_candidates(records, today=normalized.date())
        if week not in completed
    ]
    if not pending:
        return {"mode": "no-mature-week"}
    source_week = pending[0]
    outcome_source_hashes = _current_source_hashes()
    existing_path = _week_outcome_path(root, source_week)
    if existing_path.is_file():
        verified, digest = _verify_week_outcome_file(existing_path, expected_week_start=source_week)
        record = {
            "schema_version": WEEK_OUTCOME_MANIFEST_SCHEMA,
            "day": source_week.isoformat(),
            "path": str(Path("week_outcomes") / existing_path.name),
            "sha256": digest,
            "status": verified["status"],
            "row_count": verified["row_count"],
            "source_hashes": verified["source_hashes"],
        }
        _append_typed_manifest(
            _week_outcome_manifest_path(root),
            record,
            schema=WEEK_OUTCOME_MANIFEST_SCHEMA,
        )
        return {
            "mode": "week-idempotent-cache-hit",
            "source_week_start": source_week.isoformat(),
            "status": verified["status"],
            "row_count": verified["row_count"],
            "sha256": digest,
        }
    record_by_day = {date.fromisoformat(str(row["day"])): row for row in records}
    expected_days = [source_week + timedelta(days=index) for index in range(7)]
    missing_days = [day.isoformat() for day in expected_days if day not in record_by_day]

    rows: list[dict[str, Any]] = []
    status = "complete"
    reason_codes: list[str] = []
    daily_hashes: list[dict[str, str]] = []
    if missing_days:
        status = "excluded_incomplete_source_week"
        reason_codes.append("MISSING_DAILY_SOURCE")
    else:
        days: list[dict[str, Any]] = []
        for day in expected_days:
            record = record_by_day[day]
            payload, digest = _verify_day_file(root / Path(str(record["path"])), expected_day=day)
            if digest != record.get("sha256"):
                raise CollectorError("daily source hash mismatch during weekly finalization")
            days.append(payload)
            daily_hashes.append({"day": day.isoformat(), "sha256": digest})

        expected_week = source_week.isoformat()
        binance_hashes = {str(day.get("binance_snapshot_sha256")) for day in days}
        kraken_hashes = {str(day.get("kraken_universe_sha256")) for day in days}
        source_hash_sets = {json.dumps(day.get("source_hashes"), sort_keys=True) for day in days}
        asset_sets = [{str(row["base_asset"]) for row in day.get("rows", [])} for day in days]
        if (
            any(day.get("causal_week_start") != expected_week for day in days)
            or len(binance_hashes) != 1
            or len(kraken_hashes) != 1
            or len(source_hash_sets) != 1
            or any(asset_set != asset_sets[0] for asset_set in asset_sets[1:])
        ):
            status = "excluded_incomplete_source_week"
            reason_codes.append("INCONSISTENT_CAUSAL_WEEK_SOURCE")
        else:
            outcome_source_hashes = dict(days[0]["source_hashes"])
            if outcome_source_hashes != _current_source_hashes():
                raise CollectorError("frozen H-WOF source hashes changed before finalization")
            kraken_digest = next(iter(kraken_hashes))
            kraken_records = _load_typed_manifest(
                _kraken_universe_manifest_path(root),
                schema=KRAKEN_UNIVERSE_MANIFEST_SCHEMA,
            )
            matching_snapshots = [
                row for row in kraken_records if row.get("sha256") == kraken_digest
            ]
            if len(matching_snapshots) != 1:
                raise CollectorError("causal Kraken universe hash is not unique")
            snapshot_path = root / Path(str(matching_snapshots[0]["path"]))
            snapshot = _load_json(snapshot_path)
            pair_by_asset = {
                str(item["base_asset"]): str(item["pair"])
                for item in snapshot.get("pairs", [])
                if isinstance(item, Mapping)
            }
            assets = sorted(asset_sets[0])
            if set(pair_by_asset) != set(snapshot.get("base_assets", [])) or any(
                asset not in pair_by_asset for asset in assets
            ):
                raise CollectorError("causal Kraken pair mapping is incomplete")

            week_timestamp = _unix_day_start(source_week)
            entry_timestamp = week_timestamp + WEEK_SECONDS + ENTRY_DELAY_SECONDS
            exit_timestamp = entry_timestamp + WEEK_SECONDS
            for index, asset in enumerate(assets):
                daily_asset_rows = [
                    next(row for row in day["rows"] if str(row["base_asset"]) == asset)
                    for day in days
                ]
                quote_volume = sum(float(row["quote_volume"]) for row in daily_asset_rows)
                taker_buy = sum(float(row["taker_buy_quote_volume"]) for row in daily_asset_rows)
                if quote_volume <= 0 or taker_buy < 0 or taker_buy > quote_volume:
                    raise CollectorError(f"invalid aggregated weekly flow for {asset}")
                pair = pair_by_asset[asset]
                if index:
                    sleeper(request_interval_seconds)
                ohlc = fetcher(
                    KRAKEN_OHLC_URL,
                    {"pair": pair, "interval": 60, "since": entry_timestamp - 3_600},
                )
                rows.append(
                    {
                        "base_asset": asset,
                        "pair": pair,
                        "week_start": week_timestamp,
                        "quote_volume": quote_volume,
                        "taker_buy_quote_volume": taker_buy,
                        "entry_timestamp": entry_timestamp,
                        "entry_price": _kraken_open_from_payload(
                            ohlc, pair=pair, expected_timestamp=entry_timestamp
                        ),
                        "exit_timestamp": exit_timestamp,
                        "exit_price": _kraken_open_from_payload(
                            ohlc, pair=pair, expected_timestamp=exit_timestamp
                        ),
                    }
                )

    payload = {
        "schema_version": WEEK_OUTCOME_SCHEMA,
        "source_week_start": source_week.isoformat(),
        "collected_at": normalized.isoformat().replace("+00:00", "Z"),
        "status": status,
        "reason_codes": reason_codes,
        "source": KRAKEN_OHLC_URL,
        "source_params": {"interval": 60},
        "missing_days": missing_days,
        "daily_source_hashes": daily_hashes,
        "source_hashes": outcome_source_hashes,
        "row_count": len(rows),
        "rows": rows,
        "safety": {
            "public_only": True,
            "credentials_used": False,
            "orders_sent": 0,
        },
    }
    path = _week_outcome_path(root, source_week)
    _atomic_write_json(path, payload)
    verified, digest = _verify_week_outcome_file(path, expected_week_start=source_week)
    record = {
        "schema_version": WEEK_OUTCOME_MANIFEST_SCHEMA,
        "day": source_week.isoformat(),
        "path": str(Path("week_outcomes") / path.name),
        "sha256": digest,
        "status": verified["status"],
        "row_count": verified["row_count"],
        "source_hashes": verified["source_hashes"],
    }
    _append_typed_manifest(
        _week_outcome_manifest_path(root),
        record,
        schema=WEEK_OUTCOME_MANIFEST_SCHEMA,
    )
    return {
        "mode": "week-finalized",
        "source_week_start": source_week.isoformat(),
        "status": status,
        "row_count": len(rows),
        "sha256": digest,
    }


def collect_forward_day(
    *,
    root: Path,
    now: datetime,
    fetcher: HttpFetcherFn = default_http_fetcher,
    cache_only: bool = False,
    minimum_assets: int = DEFAULT_MIN_ASSETS,
    maximum_assets: int = DEFAULT_MAX_ASSETS,
) -> dict[str, Any]:
    """Capture/collect one scheduled iteration or verify its exact cache."""

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    normalized = now.astimezone(UTC)
    target_day = normalized.date() - timedelta(days=1)
    day_path = _forward_day_path(root, target_day)

    if cache_only:
        raw, digest = _verify_day_file(day_path, expected_day=target_day)
        health = healthcheck_forward(root=root, today=normalized.date(), maximum_lag_days=1)
        if not health["healthy"]:
            raise CollectorError("cache-only verification failed healthcheck")
        return {
            "mode": "cache-only",
            "day": target_day.isoformat(),
            "day_sha256": digest,
            "row_count": raw["row_count"],
            "health": health,
        }

    # Snapshot capture always happens first. It can govern future weeks only,
    # never the target day if observed after that week's start.
    _, _, binance_snapshot_created = _capture_snapshot(root, now=normalized, fetcher=fetcher)
    _, _, kraken_snapshot_created = _capture_kraken_snapshot(
        root,
        now=normalized,
        fetcher=fetcher,
        minimum_assets=minimum_assets,
        maximum_assets=maximum_assets,
    )
    if day_path.is_file():
        raw, digest = _verify_day_file(day_path, expected_day=target_day)
        records = _load_manifest(_manifest_path(root))
        record = next((row for row in records if row["day"] == target_day.isoformat()), None)
        expected_record = {
            "schema_version": MANIFEST_SCHEMA,
            "day": target_day.isoformat(),
            "path": str(Path("days") / f"{target_day.isoformat()}.json"),
            "sha256": digest,
            "row_count": raw["row_count"],
            "binance_snapshot_sha256": raw["binance_snapshot_sha256"],
            "kraken_universe_sha256": raw["kraken_universe_sha256"],
            "source_hashes": raw["source_hashes"],
        }
        if record is None:
            _append_manifest(_manifest_path(root), expected_record)
        elif record != expected_record:
            raise CollectorError("existing day is inconsistent with immutable manifest")
        return {
            "mode": "idempotent-cache-hit",
            "day": target_day.isoformat(),
            "day_sha256": digest,
            "row_count": raw["row_count"],
            "binance_snapshot_created": binance_snapshot_created,
            "kraken_snapshot_created": kraken_snapshot_created,
        }

    causal_snapshot, snapshot_digest = _latest_causal_snapshot(root, target_day=target_day)
    week_start_timestamp = _unix_day_start(_week_start(target_day))
    kraken_snapshot, kraken_universe_digest = _latest_causal_kraken_snapshot(
        root, target_day=target_day
    )
    kraken_assets = {str(asset) for asset in kraken_snapshot["base_assets"]}
    eligible = sorted(
        [
            member
            for member in universe_at([causal_snapshot], decision_timestamp=week_start_timestamp)
            if member.base_asset in kraken_assets
        ],
        key=lambda member: member.base_asset,
    )
    if not minimum_assets <= len(eligible) <= maximum_assets:
        raise CollectorError(
            f"causal intersection has {len(eligible)} assets; expected "
            f"{minimum_assets}-{maximum_assets}"
        )

    start_ms = _unix_day_start(target_day) * 1_000
    end_ms = _unix_day_start(target_day + timedelta(days=1)) * 1_000
    rows: list[dict[str, Any]] = []
    for member in eligible:
        candles = fetch_daily_klines(
            symbol=member.symbol,
            base_asset=member.base_asset,
            start_ms=start_ms,
            end_ms=end_ms,
            fetcher=fetcher,
        )
        if len(candles) != 1 or candles[0]["timestamp"] != start_ms // 1_000:
            raise CollectorError(f"closed daily kline missing for {member.symbol}")
        rows.extend(candles)
    payload = {
        "schema_version": FORWARD_SCHEMA,
        "day": target_day.isoformat(),
        "collected_at": normalized.isoformat().replace("+00:00", "Z"),
        "source": DAILY_KLINES_URL,
        "source_window": {"start_ms": start_ms, "end_ms_exclusive": end_ms},
        "causal_week_start": _week_start(target_day).isoformat(),
        "binance_snapshot_observed_at": causal_snapshot.observed_at,
        "binance_snapshot_sha256": snapshot_digest,
        "kraken_universe_observed_at": kraken_snapshot["observed_at"],
        "kraken_universe_sha256": kraken_universe_digest,
        "source_hashes": _current_source_hashes(),
        "row_count": len(rows),
        "rows": rows,
    }
    _atomic_write_json(day_path, payload)
    digest = sha256_file(day_path)
    if digest is None:
        raise CollectorError("could not hash forward day after write")
    record = {
        "schema_version": MANIFEST_SCHEMA,
        "day": target_day.isoformat(),
        "path": str(Path("days") / f"{target_day.isoformat()}.json"),
        "sha256": digest,
        "row_count": len(rows),
        "binance_snapshot_sha256": snapshot_digest,
        "kraken_universe_sha256": kraken_universe_digest,
        "source_hashes": payload["source_hashes"],
    }
    _append_manifest(_manifest_path(root), record)
    return {
        "mode": "network",
        "day": target_day.isoformat(),
        "day_sha256": digest,
        "row_count": len(rows),
        "binance_snapshot_created": binance_snapshot_created,
        "kraken_snapshot_created": kraken_snapshot_created,
    }


def healthcheck_forward(*, root: Path, today: date, maximum_lag_days: int = 1) -> dict[str, Any]:
    """Verify the whole local journal and return a scheduler-friendly digest."""

    errors: list[str] = []
    records: list[dict[str, Any]] = []
    snapshots: list[UniverseSnapshot] = []
    current_source_hashes = _current_source_hashes()
    try:
        records = _load_manifest(_manifest_path(root))
        snapshots = load_universe_snapshots(_snapshot_log(root))
        for snapshot in snapshots:
            snapshot_path = _snapshot_day_path(
                root, datetime.fromtimestamp(snapshot.observed_at, tz=UTC).date()
            )
            if (
                not snapshot_path.is_file()
                or parse_universe_snapshot(_load_json(snapshot_path)) != snapshot
            ):
                errors.append(f"snapshot_file_mismatch:{snapshot.observed_at}")
    except CollectorError as exc:
        errors.append(str(exc))

    try:
        kraken_records = _load_typed_manifest(
            _kraken_universe_manifest_path(root),
            schema=KRAKEN_UNIVERSE_MANIFEST_SCHEMA,
        )
        if not kraken_records:
            errors.append("no_kraken_universe_snapshots")
        for record in kraken_records:
            expected = Path("kraken_universe_days") / f"{record['day']}.json"
            if Path(str(record.get("path"))) != expected:
                raise CollectorError("Kraken universe manifest path is not canonical")
            path = root / expected
            raw = _load_json(path)
            if (
                not isinstance(raw, dict)
                or raw.get("schema_version") != UNIVERSE_SCHEMA
                or sha256_file(path) != record.get("sha256")
                or raw.get("observed_at") != record.get("observed_at")
                or len(raw.get("base_assets", [])) != record.get("asset_count")
                or raw.get("source") != KRAKEN_ASSET_PAIRS_URL
            ):
                raise CollectorError("Kraken universe snapshot provenance mismatch")
    except (CollectorError, KeyError, TypeError) as exc:
        errors.append(str(exc))

    verified_records: list[str] = []
    for record in records:
        try:
            day = date.fromisoformat(str(record["day"]))
            relative = Path(str(record["path"]))
            expected_relative = Path("days") / f"{day.isoformat()}.json"
            if relative != expected_relative:
                raise CollectorError("manifest path is not the canonical day path")
            path = root / relative
            raw, digest = _verify_day_file(path, expected_day=day)
            if (
                digest != record.get("sha256")
                or raw["row_count"] != record.get("row_count")
                or raw["binance_snapshot_sha256"] != record.get("binance_snapshot_sha256")
                or raw["kraken_universe_sha256"] != record.get("kraken_universe_sha256")
                or raw["source_hashes"] != record.get("source_hashes")
                or raw["source_hashes"] != current_source_hashes
            ):
                raise CollectorError("manifest digest or row count mismatch")
            verified_records.append(
                f"{record['day']}:{digest}:{record['binance_snapshot_sha256']}:"
                f"{record['kraken_universe_sha256']}:"
                f"{json.dumps(record['source_hashes'], sort_keys=True)}"
            )
        except (CollectorError, KeyError, ValueError) as exc:
            errors.append(f"manifest_record_invalid:{record.get('day')}:{exc}")

    latest_day = date.fromisoformat(records[-1]["day"]) if records else None
    lag_days = (today - latest_day).days - 1 if latest_day is not None else None
    bootstrap_pending = False
    if latest_day is None and snapshots:
        first_snapshot_day = datetime.fromtimestamp(
            min(row.observed_at for row in snapshots), tz=UTC
        ).date()
        first_causal_week = _week_start(first_snapshot_day) + timedelta(days=7)
        bootstrap_pending = today <= first_causal_week + timedelta(days=1)
    if latest_day is None:
        if not bootstrap_pending:
            errors.append("no_forward_days")
    elif latest_day >= today:
        errors.append(f"forward_day_not_closed:{latest_day.isoformat()}")
    elif lag_days > maximum_lag_days:
        errors.append(f"forward_lag_days:{lag_days}")
    verified_outcomes: list[str] = []
    outcome_records: list[dict[str, Any]] = []
    try:
        outcome_records = _load_typed_manifest(
            _week_outcome_manifest_path(root), schema=WEEK_OUTCOME_MANIFEST_SCHEMA
        )
        for record in outcome_records:
            week = date.fromisoformat(str(record["day"]))
            relative = Path(str(record.get("path")))
            expected_relative = Path("week_outcomes") / f"{week.isoformat()}.json"
            if relative != expected_relative:
                raise CollectorError("week outcome manifest path is not canonical")
            payload, outcome_digest = _verify_week_outcome_file(
                root / relative, expected_week_start=week
            )
            if (
                outcome_digest != record.get("sha256")
                or payload["status"] != record.get("status")
                or payload["row_count"] != record.get("row_count")
                or payload["source_hashes"] != record.get("source_hashes")
                or payload["source_hashes"] != current_source_hashes
            ):
                raise CollectorError("week outcome manifest mismatch")
            verified_outcomes.append(
                f"{week.isoformat()}:{outcome_digest}:{payload['status']}:{payload['row_count']}"
                f":{json.dumps(payload['source_hashes'], sort_keys=True)}"
            )
        completed_weeks = {date.fromisoformat(str(record["day"])) for record in outcome_records}
        overdue = [
            week.isoformat()
            for week in _source_week_candidates(records, today=today)
            if week not in completed_weeks
        ]
        if overdue:
            errors.append(f"mature_week_outcomes_missing:{','.join(overdue)}")
    except (CollectorError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"week_outcome_invalid:{exc}")

    digest_material = [*verified_records, "--week-outcomes--", *verified_outcomes]
    digest = hashlib.sha256("\n".join(digest_material).encode()).hexdigest()
    return {
        "schema_version": "hwof002-forward-health-v1",
        "mode": "bootstrap-pending" if bootstrap_pending else "journal",
        "healthy": not errors,
        "latest_day": latest_day.isoformat() if latest_day else None,
        "lag_days": lag_days,
        "manifest_records": len(records),
        "week_outcome_records": len(outcome_records),
        "journal_sha256": digest,
        "errors": errors,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "collect",
            "collect-scheduled",
            "snapshot",
            "snapshot-kraken",
            "healthcheck",
            "digest",
        ),
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--as-of-date", type=date.fromisoformat)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--minimum-assets", type=int, default=DEFAULT_MIN_ASSETS)
    parser.add_argument("--maximum-assets", type=int, default=DEFAULT_MAX_ASSETS)
    parser.add_argument("--maximum-lag-days", type=int, default=1)
    return parser


def main() -> int:
    args = _parser().parse_args()
    now = datetime.now(UTC)
    if args.as_of_date is not None:
        now = datetime.combine(args.as_of_date, time(hour=1), tzinfo=UTC)
    try:
        if (
            args.as_of_date is not None
            and args.command in {"snapshot", "snapshot-kraken", "collect", "collect-scheduled"}
            and not args.cache_only
        ):
            raise ValueError(
                "historical network capture is forbidden; --as-of-date is verification-only"
            )
        if args.command == "snapshot":
            if args.cache_only:
                raise ValueError("snapshot cannot run with --cache-only")
            snapshot, digest, created = _capture_snapshot(
                args.root, now=now, fetcher=default_http_fetcher
            )
            result = {
                "created": created,
                "observed_at": snapshot.observed_at,
                "sha256": digest,
                "members": len(snapshot.members),
            }
        elif args.command == "snapshot-kraken":
            if args.cache_only:
                raise ValueError("snapshot-kraken cannot run with --cache-only")
            snapshot, digest, created = _capture_kraken_snapshot(
                args.root,
                now=now,
                fetcher=default_http_fetcher,
                minimum_assets=args.minimum_assets,
                maximum_assets=args.maximum_assets,
            )
            result = {
                "created": created,
                "observed_at": snapshot["observed_at"],
                "sha256": digest,
                "assets": len(snapshot["base_assets"]),
                "source": KRAKEN_ASSET_PAIRS_URL,
            }
        elif args.command in {"collect", "collect-scheduled"}:
            try:
                result = collect_forward_day(
                    root=args.root,
                    now=now,
                    cache_only=args.cache_only,
                    minimum_assets=args.minimum_assets,
                    maximum_assets=args.maximum_assets,
                )
                if not args.cache_only:
                    result["week_outcome"] = collect_mature_week_outcome(
                        root=args.root,
                        now=now,
                        fetcher=default_http_fetcher,
                    )
            except CollectorError as exc:
                bootstrap_reasons = {
                    "bootstrap incomplete: no universe snapshot predates target week",
                    "bootstrap incomplete: no Kraken universe predates target week",
                }
                if args.command != "collect-scheduled" or str(exc) not in bootstrap_reasons:
                    raise
                result = {
                    "healthy": True,
                    "mode": "bootstrap-pending",
                    "reason": str(exc),
                    "snapshots_captured": True,
                }
        else:
            result = healthcheck_forward(
                root=args.root,
                today=now.date(),
                maximum_lag_days=args.maximum_lag_days,
            )
            if args.command == "digest":
                result = {
                    "healthy": result["healthy"],
                    "latest_day": result["latest_day"],
                    "week_outcome_records": result["week_outcome_records"],
                    "journal_sha256": result["journal_sha256"],
                }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("healthy", True) else 2
    except (CollectorError, OSError, RuntimeError, ValueError) as exc:
        print(f"H-WOF-002 forward blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
