"""Operate the forward-only, no-order H-WOF-002 data journal.

The scheduled workflow is intentionally two days causal at bootstrap:

1. capture today's public ``exchangeInfo`` snapshot;
2. collect yesterday's fully closed 1d klines using the latest snapshot that
   already existed before the start of that day's UTC week;
3. append one immutable daily artifact and its SHA-256 manifest record.

No return, future price, position, paper fill, live order or credential is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
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

FORWARD_SCHEMA = "hwof002-forward-day-v1"
MANIFEST_SCHEMA = "hwof002-forward-manifest-v1"
UNIVERSE_SCHEMA = "hwof002-forward-kraken-universe-v1"
KRAKEN_ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"
KRAKEN_UNIVERSE_MANIFEST_SCHEMA = "hwof002-kraken-universe-manifest-v1"
DEFAULT_ROOT = Path("data/collector_cache/world_order_flow_forward")
DEFAULT_MIN_ASSETS = 30
DEFAULT_MAX_ASSETS = 80
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


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
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
        snapshot = fetch_exchange_info_snapshot(
            fetcher=fetcher, observed_at=normalized
        )
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
        if previous is None or (
            KRAKEN_QUOTE_PRIORITY[quote], candidate["pair"]
        ) < (
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


def _append_typed_manifest(
    path: Path, record: dict[str, Any], *, schema: str
) -> bool:
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


def _latest_causal_kraken_snapshot(
    root: Path, *, target_day: date
) -> tuple[dict[str, Any], str]:
    known_by = _unix_day_start(_week_start(target_day))
    records = _load_typed_manifest(
        _kraken_universe_manifest_path(root),
        schema=KRAKEN_UNIVERSE_MANIFEST_SCHEMA,
    )
    eligible = [row for row in records if int(row["observed_at"]) <= known_by]
    if not eligible:
        raise CollectorError(
            "bootstrap incomplete: no Kraken universe predates target week"
        )
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
        raise CollectorError(
            "bootstrap incomplete: no universe snapshot predates target week"
        )
    day_path = _snapshot_day_path(
        root, datetime.fromtimestamp(snapshot.observed_at, tz=UTC).date()
    )
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
        health = healthcheck_forward(
            root=root, today=normalized.date(), maximum_lag_days=1
        )
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
    _, _, binance_snapshot_created = _capture_snapshot(
        root, now=normalized, fetcher=fetcher
    )
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

    causal_snapshot, snapshot_digest = _latest_causal_snapshot(
        root, target_day=target_day
    )
    week_start_timestamp = _unix_day_start(_week_start(target_day))
    kraken_snapshot, kraken_universe_digest = _latest_causal_kraken_snapshot(
        root, target_day=target_day
    )
    kraken_assets = {str(asset) for asset in kraken_snapshot["base_assets"]}
    eligible = sorted(
        [
            member
            for member in universe_at(
                [causal_snapshot], decision_timestamp=week_start_timestamp
            )
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


def healthcheck_forward(
    *, root: Path, today: date, maximum_lag_days: int = 1
) -> dict[str, Any]:
    """Verify the whole local journal and return a scheduler-friendly digest."""

    errors: list[str] = []
    records: list[dict[str, Any]] = []
    try:
        records = _load_manifest(_manifest_path(root))
        snapshots = load_universe_snapshots(_snapshot_log(root))
        for snapshot in snapshots:
            snapshot_path = _snapshot_day_path(
                root, datetime.fromtimestamp(snapshot.observed_at, tz=UTC).date()
            )
            if not snapshot_path.is_file() or parse_universe_snapshot(
                _load_json(snapshot_path)
            ) != snapshot:
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
                or raw["binance_snapshot_sha256"]
                != record.get("binance_snapshot_sha256")
                or raw["kraken_universe_sha256"]
                != record.get("kraken_universe_sha256")
            ):
                raise CollectorError("manifest digest or row count mismatch")
            verified_records.append(
                f"{record['day']}:{digest}:{record['binance_snapshot_sha256']}:"
                f"{record['kraken_universe_sha256']}"
            )
        except (CollectorError, KeyError, ValueError) as exc:
            errors.append(f"manifest_record_invalid:{record.get('day')}:{exc}")

    latest_day = date.fromisoformat(records[-1]["day"]) if records else None
    lag_days = (today - latest_day).days - 1 if latest_day is not None else None
    if latest_day is None:
        errors.append("no_forward_days")
    elif latest_day >= today:
        errors.append(f"forward_day_not_closed:{latest_day.isoformat()}")
    elif lag_days > maximum_lag_days:
        errors.append(f"forward_lag_days:{lag_days}")
    digest = hashlib.sha256("\n".join(verified_records).encode()).hexdigest()
    return {
        "schema_version": "hwof002-forward-health-v1",
        "healthy": not errors,
        "latest_day": latest_day.isoformat() if latest_day else None,
        "lag_days": lag_days,
        "manifest_records": len(records),
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
            and args.command
            in {"snapshot", "snapshot-kraken", "collect", "collect-scheduled"}
            and not args.cache_only
        ):
            raise ValueError(
                "historical network capture is forbidden; --as-of-date is "
                "verification-only"
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
                    "journal_sha256": result["journal_sha256"],
                }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("healthy", True) else 2
    except (CollectorError, OSError, RuntimeError, ValueError) as exc:
        print(f"H-WOF-002 forward blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
