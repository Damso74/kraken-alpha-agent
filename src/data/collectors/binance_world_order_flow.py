"""Causal public-data collector helpers for H-WOF-002.

The module has two deliberately separate responsibilities:

* append timestamped Binance ``exchangeInfo`` snapshots for a forward,
  point-in-time universe;
* collect official daily klines for the primary aggregate-flow proxy;
* inspect a bounded Binance Vision ``aggTrades`` archive for an equivalence
  audit, never as the multi-year primary corpus.

An exchange-info snapshot observed today is never accepted as evidence for a
historical rebalance.  This fail-closed rule prevents the current symbol list
from silently introducing survivorship bias into a historical backtest.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ._common import CollectorError, HttpFetcherFn, default_http_fetcher

EXCHANGE_INFO_URL = "https://data-api.binance.vision/api/v3/exchangeInfo"
DAILY_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
BINANCE_VISION_BASE_URL = "https://data.binance.vision/data/spot/monthly/aggTrades"
BINANCE_VISION_DAILY_BASE_URL = "https://data.binance.vision/data/spot/daily/aggTrades"
DEFAULT_QUOTES = ("USDT",)
SNAPSHOT_SCHEMA = "hwof002-universe-snapshot-v1"
FLOW_SCHEMA = "hwof002-weekly-flow-v1"
WEEK_SECONDS = 7 * 86_400
DAY_MILLISECONDS = 86_400_000
MAX_KLINES_PER_PAGE = 1_000
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

BytesFetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class UniverseMember:
    symbol: str
    base_asset: str
    quote_asset: str
    status: str


@dataclass(frozen=True)
class UniverseSnapshot:
    observed_at: int
    observed_at_iso: str
    source: str
    members: tuple[UniverseMember, ...]
    schema_version: str = SNAPSHOT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["members"] = [asdict(member) for member in self.members]
        return payload


@dataclass(frozen=True)
class ArchiveManifestEntry:
    symbol: str
    period: str
    cadence: str
    url: str
    sha256: str


def _unix_timestamp(value: datetime | None) -> tuple[int, str]:
    moment = value or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    normalized = moment.astimezone(UTC)
    return int(normalized.timestamp()), normalized.isoformat().replace("+00:00", "Z")


def parse_exchange_info(
    payload: Any,
    *,
    observed_at: datetime | None = None,
    allowed_quotes: Sequence[str] = DEFAULT_QUOTES,
) -> UniverseSnapshot:
    """Normalize one public exchange-info response into a causal snapshot."""

    if not isinstance(payload, Mapping) or not isinstance(payload.get("symbols"), list):
        raise CollectorError("Binance exchangeInfo payload has no symbols list")
    quotes = {str(quote).upper() for quote in allowed_quotes}
    if not quotes:
        raise ValueError("allowed_quotes must not be empty")

    members: dict[str, UniverseMember] = {}
    for raw in payload["symbols"]:
        if not isinstance(raw, Mapping):
            raise CollectorError("Binance exchangeInfo symbol row is not an object")
        symbol = str(raw.get("symbol", "")).upper()
        base = str(raw.get("baseAsset", "")).upper()
        quote = str(raw.get("quoteAsset", "")).upper()
        status = str(raw.get("status", "")).upper()
        is_spot = raw.get("isSpotTradingAllowed", True)
        if quote not in quotes or status != "TRADING" or is_spot is not True:
            continue
        if not symbol or not base or symbol != f"{base}{quote}":
            raise CollectorError(f"invalid Binance symbol metadata: {raw!r}")
        member = UniverseMember(symbol, base, quote, status)
        previous = members.get(base)
        if previous is not None:
            raise CollectorError(
                f"multiple eligible quote pairs for base asset {base}: "
                f"{previous.symbol}, {symbol}"
            )
        members[base] = member

    timestamp, iso = _unix_timestamp(observed_at)
    return UniverseSnapshot(
        observed_at=timestamp,
        observed_at_iso=iso,
        source=EXCHANGE_INFO_URL,
        members=tuple(sorted(members.values(), key=lambda item: item.base_asset)),
    )


def fetch_exchange_info_snapshot(
    *,
    fetcher: HttpFetcherFn = default_http_fetcher,
    observed_at: datetime | None = None,
    allowed_quotes: Sequence[str] = DEFAULT_QUOTES,
) -> UniverseSnapshot:
    payload = fetcher(EXCHANGE_INFO_URL, None)
    return parse_exchange_info(
        payload, observed_at=observed_at, allowed_quotes=allowed_quotes
    )


def append_universe_snapshot(path: Path, snapshot: UniverseSnapshot) -> None:
    """Append a snapshot, rejecting timestamp rewrites and non-monotonic history."""

    existing = load_universe_snapshots(path) if path.exists() else []
    if existing and snapshot.observed_at <= existing[-1].observed_at:
        raise CollectorError("universe snapshots must be strictly append-only")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(snapshot.to_dict(), sort_keys=True) + "\n")


def _snapshot_from_dict(raw: Any) -> UniverseSnapshot:
    if not isinstance(raw, Mapping) or raw.get("schema_version") != SNAPSHOT_SCHEMA:
        raise CollectorError("invalid H-WOF-002 universe snapshot schema")
    observed_at = raw.get("observed_at")
    if isinstance(observed_at, bool) or not isinstance(observed_at, int):
        raise CollectorError("invalid universe snapshot timestamp")
    members_raw = raw.get("members")
    if not isinstance(members_raw, list):
        raise CollectorError("invalid universe snapshot members")
    members: list[UniverseMember] = []
    for item in members_raw:
        if not isinstance(item, Mapping):
            raise CollectorError("invalid universe member")
        member = UniverseMember(
            symbol=str(item.get("symbol", "")).upper(),
            base_asset=str(item.get("base_asset", "")).upper(),
            quote_asset=str(item.get("quote_asset", "")).upper(),
            status=str(item.get("status", "")).upper(),
        )
        if (
            not member.symbol
            or not member.base_asset
            or member.status != "TRADING"
            or member.symbol != f"{member.base_asset}{member.quote_asset}"
        ):
            raise CollectorError("invalid universe member fields")
        members.append(member)
    if len({member.base_asset for member in members}) != len(members):
        raise CollectorError("duplicate base asset in universe snapshot")
    return UniverseSnapshot(
        observed_at=observed_at,
        observed_at_iso=str(raw.get("observed_at_iso", "")),
        source=str(raw.get("source", "")),
        members=tuple(sorted(members, key=lambda item: item.base_asset)),
    )


def parse_universe_snapshot(raw: Any) -> UniverseSnapshot:
    """Public strict parser for snapshots embedded in immutable bundles."""

    return _snapshot_from_dict(raw)


def load_universe_snapshots(path: Path) -> list[UniverseSnapshot]:
    if not path.is_file():
        raise CollectorError(f"missing universe snapshot log: {path}")
    snapshots: list[UniverseSnapshot] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CollectorError(
                f"invalid universe snapshot JSON at line {line_number}"
            ) from exc
        snapshot = _snapshot_from_dict(raw)
        if snapshots and snapshot.observed_at <= snapshots[-1].observed_at:
            raise CollectorError("universe snapshot log is not strictly chronological")
        snapshots.append(snapshot)
    if not snapshots:
        raise CollectorError("empty universe snapshot log")
    return snapshots


def universe_at(
    snapshots: Sequence[UniverseSnapshot], *, decision_timestamp: int
) -> tuple[UniverseMember, ...]:
    """Return the latest universe known by a decision, never a later snapshot."""

    eligible = [row for row in snapshots if row.observed_at <= decision_timestamp]
    if not eligible:
        raise CollectorError(
            "no point-in-time universe snapshot existed before the decision"
        )
    return max(eligible, key=lambda row: row.observed_at).members


def monthly_aggtrades_url(symbol: str, month: str) -> str:
    normalized = symbol.upper()
    if not normalized.isalnum() or not _MONTH_RE.fullmatch(month):
        raise ValueError("invalid Binance Vision symbol or month")
    filename = f"{normalized}-aggTrades-{month}.zip"
    return f"{BINANCE_VISION_BASE_URL}/{normalized}/{filename}"


def daily_aggtrades_url(symbol: str, day: str) -> str:
    normalized = symbol.upper()
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("invalid Binance Vision day") from exc
    if not normalized.isalnum():
        raise ValueError("invalid Binance Vision symbol")
    filename = f"{normalized}-aggTrades-{day}.zip"
    return f"{BINANCE_VISION_DAILY_BASE_URL}/{normalized}/{filename}"


def _non_negative_float(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise CollectorError(f"invalid Binance {label}: {value!r}")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CollectorError(f"invalid Binance {label}: {value!r}") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise CollectorError(f"invalid Binance {label}: {value!r}")
    return parsed


def parse_daily_klines(
    payload: Any, *, symbol: str, base_asset: str
) -> list[dict[str, Any]]:
    """Parse one public daily-kline page without imputing missing days."""

    if not isinstance(payload, list):
        raise CollectorError("Binance klines payload is not a list")
    rows: dict[int, dict[str, Any]] = {}
    previous: int | None = None
    for raw in payload:
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, (str, bytes))
            or len(raw) < 11
        ):
            raise CollectorError("Binance kline row has fewer than 11 fields")
        open_ms = raw[0]
        if isinstance(open_ms, bool) or not isinstance(open_ms, int):
            raise CollectorError("invalid Binance daily kline timestamp")
        if open_ms < 0 or open_ms % DAY_MILLISECONDS:
            raise CollectorError("Binance kline is not on a UTC day boundary")
        if previous is not None and open_ms < previous:
            raise CollectorError("Binance daily klines are out of order")
        previous = open_ms
        quote_volume = _non_negative_float(raw[7], label="quote volume")
        taker_buy = _non_negative_float(raw[10], label="taker buy quote volume")
        if quote_volume <= 0 or taker_buy > quote_volume:
            raise CollectorError("invalid Binance kline flow volumes")
        row = {
            "symbol": symbol.upper(),
            "base_asset": base_asset.upper(),
            "timestamp": open_ms // 1_000,
            "quote_volume": quote_volume,
            "taker_buy_quote_volume": taker_buy,
        }
        previous_row = rows.get(row["timestamp"])
        if previous_row is not None and previous_row != row:
            raise CollectorError("conflicting duplicate Binance daily kline")
        rows[row["timestamp"]] = row
    return [rows[timestamp] for timestamp in sorted(rows)]


def fetch_daily_klines(
    *,
    symbol: str,
    base_asset: str,
    start_ms: int,
    end_ms: int,
    fetcher: HttpFetcherFn = default_http_fetcher,
    max_pages: int = 100,
) -> list[dict[str, Any]]:
    """Fetch one symbol's daily aggregate flow over half-open ``[start, end)``."""

    if end_ms <= start_ms or start_ms < 0 or max_pages <= 0:
        raise ValueError("invalid Binance daily-kline request")
    if symbol.upper() != f"{base_asset.upper()}USDT":
        raise ValueError("H-WOF-002 primary collector requires BASEUSDT")
    cursor = start_ms
    rows: dict[int, dict[str, Any]] = {}
    for page_index in range(max_pages):
        payload = fetcher(
            DAILY_KLINES_URL,
            {
                "symbol": symbol.upper(),
                "interval": "1d",
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": MAX_KLINES_PER_PAGE,
            },
        )
        raw_size = len(payload) if isinstance(payload, list) else 0
        page = parse_daily_klines(payload, symbol=symbol, base_asset=base_asset)
        if not page:
            return [rows[timestamp] for timestamp in sorted(rows)]
        for row in page:
            timestamp_ms = int(row["timestamp"]) * 1_000
            if not start_ms <= timestamp_ms < end_ms:
                raise CollectorError("Binance kline outside requested window")
            previous = rows.get(int(row["timestamp"]))
            if previous is not None and previous != row:
                raise CollectorError("conflicting paginated Binance daily kline")
            rows[int(row["timestamp"])] = row
        next_cursor = int(page[-1]["timestamp"]) * 1_000 + DAY_MILLISECONDS
        if next_cursor <= cursor:
            raise CollectorError("Binance daily-kline cursor did not advance")
        cursor = next_cursor
        if raw_size < MAX_KLINES_PER_PAGE or cursor >= end_ms:
            return [rows[timestamp] for timestamp in sorted(rows)]
        if page_index + 1 == max_pages:
            break
    raise CollectorError(f"Binance daily klines exceeded max_pages={max_pages}")


def fetch_dynamic_universe_week(
    *,
    snapshots: Sequence[UniverseSnapshot],
    week_start: int,
    kraken_base_assets: Sequence[str],
    fetcher: HttpFetcherFn = default_http_fetcher,
    minimum_assets: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect one complete week for the causal Binance/Kraken intersection.

    Any missing daily candle aborts the entire week.  The function never
    substitutes a lower-ranked or newly listed asset after seeing data.
    """

    moment = datetime.fromtimestamp(week_start, tz=UTC)
    if (
        moment.weekday() != 0
        or moment.hour
        or moment.minute
        or moment.second
        or minimum_assets <= 0
    ):
        raise ValueError("week_start must be a UTC Monday and minimum_assets positive")
    kraken = {str(asset).upper() for asset in kraken_base_assets}
    members = [
        member
        for member in universe_at(snapshots, decision_timestamp=week_start)
        if member.base_asset in kraken
    ]
    if len(members) < minimum_assets:
        raise CollectorError(
            f"causal dynamic universe has {len(members)} assets; need {minimum_assets}"
        )
    start_ms = week_start * 1_000
    end_ms = (week_start + WEEK_SECONDS) * 1_000
    weekly: list[dict[str, Any]] = []
    for member in sorted(members, key=lambda item: item.base_asset):
        daily = fetch_daily_klines(
            symbol=member.symbol,
            base_asset=member.base_asset,
            start_ms=start_ms,
            end_ms=end_ms,
            fetcher=fetcher,
        )
        rows = aggregate_daily_klines_to_weeks(daily)
        if len(rows) != 1 or rows[0]["week_start"] != week_start:
            raise CollectorError(
                f"incomplete dynamic-universe week for {member.symbol}"
            )
        weekly.extend(rows)
    return weekly, {
        "week_start": week_start,
        "binance_snapshot_observed_at": max(
            row.observed_at for row in snapshots if row.observed_at <= week_start
        ),
        "eligible_asset_count": len(members),
        "complete_asset_count": len(weekly),
        "source": DAILY_KLINES_URL,
    }


def aggregate_daily_klines_to_weeks(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate only complete Monday-to-Monday sets of seven daily candles."""

    daily: dict[tuple[str, int], Mapping[str, Any]] = {}
    for row in rows:
        base = str(row.get("base_asset", "")).upper()
        timestamp = row.get("timestamp")
        if not base or isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise CollectorError("invalid daily kline identity")
        key = (base, timestamp)
        if key in daily and daily[key] != row:
            raise CollectorError("conflicting duplicate daily kline input")
        daily[key] = row
    output: list[dict[str, Any]] = []
    bases = sorted({key[0] for key in daily})
    for base in bases:
        timestamps = sorted(timestamp for asset, timestamp in daily if asset == base)
        if not timestamps:
            continue
        first = timestamps[0]
        first_monday = first - datetime.fromtimestamp(first, tz=UTC).weekday() * 86_400
        last = timestamps[-1]
        week = first_monday
        while week + 6 * 86_400 <= last:
            days = [week + offset * 86_400 for offset in range(7)]
            if all((base, day) in daily for day in days):
                quote = sum(float(daily[(base, day)]["quote_volume"]) for day in days)
                buy = sum(
                    float(daily[(base, day)]["taker_buy_quote_volume"])
                    for day in days
                )
                output.append(
                    {
                        "schema_version": FLOW_SCHEMA,
                        "symbol": str(daily[(base, days[0])]["symbol"]),
                        "base_asset": base,
                        "week_start": week,
                        "quote_volume": quote,
                        "taker_buy_quote_volume": buy,
                        "source_days": 7,
                        "source_kind": "binance_spot_1d_klines_proxy",
                    }
                )
            week += WEEK_SECONDS
    return output


def compare_weekly_flow_sources(
    kline_rows: Sequence[Mapping[str, Any]],
    aggtrade_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bounded diagnostic comparing kline proxy and tick-derived aggregates."""

    def scores(source: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int], float]:
        result: dict[tuple[str, int], float] = {}
        for row in source:
            quote = float(row["quote_volume"])
            buy = float(row["taker_buy_quote_volume"])
            if quote <= 0 or buy < 0 or buy > quote:
                raise CollectorError("invalid weekly flow in equivalence audit")
            result[(str(row["base_asset"]), int(row["week_start"]))] = (
                2.0 * buy - quote
            ) / quote
        return result

    primary = scores(kline_rows)
    ticks = scores(aggtrade_rows)
    keys = sorted(set(primary) & set(ticks))
    differences = [abs(primary[key] - ticks[key]) for key in keys]
    sign_matches = [
        (primary[key] > 0) == (ticks[key] > 0) for key in keys
    ]
    return {
        "matched_asset_weeks": len(keys),
        "mean_absolute_imbalance_error": (
            sum(differences) / len(differences) if differences else None
        ),
        "max_absolute_imbalance_error": max(differences) if differences else None,
        "sign_agreement_rate": (
            sum(sign_matches) / len(sign_matches) if sign_matches else None
        ),
        "diagnostic_only": True,
    }


def compare_daily_flow_sources(
    kline_rows: Sequence[Mapping[str, Any]],
    aggtrade_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Diagnostic equality check for the preregistered one-day tick sample."""

    def scores(source: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int], float]:
        result: dict[tuple[str, int], float] = {}
        for row in source:
            quote = float(row["quote_volume"])
            buy = float(row["taker_buy_quote_volume"])
            if quote <= 0 or buy < 0 or buy > quote:
                raise CollectorError("invalid daily flow in equivalence audit")
            result[(str(row["base_asset"]), int(row["timestamp"]))] = (
                2.0 * buy - quote
            ) / quote
        return result

    primary = scores(kline_rows)
    ticks = scores(aggtrade_rows)
    keys = sorted(set(primary) & set(ticks))
    differences = [abs(primary[key] - ticks[key]) for key in keys]
    return {
        "matched_asset_days": len(keys),
        "mean_absolute_imbalance_error": (
            sum(differences) / len(differences) if differences else None
        ),
        "max_absolute_imbalance_error": max(differences) if differences else None,
        "sign_agreement_rate": (
            sum((primary[key] > 0) == (ticks[key] > 0) for key in keys) / len(keys)
            if keys
            else None
        ),
        "diagnostic_only": True,
    }


def default_bytes_fetcher(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
            return response.read()
    except OSError as exc:
        raise CollectorError(f"failed to download {url}: {exc}") from exc


def _normalize_trade_timestamp(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise CollectorError(f"invalid aggTrades timestamp: {raw!r}") from exc
    # Binance Vision switched spot timestamps from milliseconds to microseconds
    # in 2025. Both representations normalize to UTC unix seconds here.
    divisor = 1_000_000 if value >= 10**15 else 1_000
    timestamp = value // divisor
    if timestamp <= 0:
        raise CollectorError(f"invalid aggTrades timestamp: {raw!r}")
    return timestamp


def aggregate_aggtrades_zip(
    payload: bytes, *, symbol: str, base_asset: str, cadence: str = "weekly"
) -> list[dict[str, Any]]:
    """Aggregate one official aggTrades ZIP into UTC days or ISO weeks."""

    if cadence not in {"daily", "weekly"}:
        raise ValueError("cadence must be daily or weekly")

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise CollectorError("invalid Binance Vision ZIP") from exc
    names = [name for name in archive.namelist() if not name.endswith("/")]
    if len(names) != 1 or Path(names[0]).name != names[0]:
        raise CollectorError("Binance Vision ZIP must contain one flat CSV file")

    buckets: dict[int, list[float | int]] = {}
    try:
        with archive.open(names[0]) as binary:
            reader = csv.reader(io.TextIOWrapper(binary, encoding="utf-8", newline=""))
            for row_number, row in enumerate(reader, 1):
                if row_number == 1 and row and not row[0].isdigit():
                    continue
                if len(row) < 7:
                    raise CollectorError("aggTrades CSV row has fewer than 7 columns")
                try:
                    price = float(row[1])
                    quantity = float(row[2])
                except ValueError as exc:
                    raise CollectorError("invalid aggTrades price or quantity") from exc
                if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0:
                    raise CollectorError("non-positive aggTrades price or quantity")
                timestamp = _normalize_trade_timestamp(row[5])
                buyer_maker = row[6].strip().lower()
                if buyer_maker not in {"true", "false"}:
                    raise CollectorError("invalid aggTrades buyer-maker flag")
                day_start = timestamp - timestamp % 86_400
                bucket_start = day_start
                if cadence == "weekly":
                    bucket_start -= (
                        datetime.fromtimestamp(day_start, tz=UTC).weekday() * 86_400
                    )
                quote_volume = price * quantity
                bucket = buckets.setdefault(bucket_start, [0.0, 0.0, 0])
                bucket[0] = float(bucket[0]) + quote_volume
                if buyer_maker == "false":
                    bucket[1] = float(bucket[1]) + quote_volume
                bucket[2] = int(bucket[2]) + 1
    finally:
        archive.close()

    return [
        {
            "schema_version": FLOW_SCHEMA,
            "symbol": symbol.upper(),
            "base_asset": base_asset.upper(),
            ("timestamp" if cadence == "daily" else "week_start"): bucket_start,
            "quote_volume": values[0],
            "taker_buy_quote_volume": values[1],
            "trade_count": values[2],
        }
        for bucket_start, values in sorted(buckets.items())
    ]


def fetch_monthly_aggtrades(
    *,
    symbol: str,
    base_asset: str,
    month: str,
    expected_sha256: str,
    fetcher: BytesFetcher = default_bytes_fetcher,
) -> tuple[list[dict[str, Any]], ArchiveManifestEntry]:
    """Download one immutable archive, requiring a preregistered SHA-256."""

    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
    url = monthly_aggtrades_url(symbol, month)
    payload = fetcher(url)
    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected_sha256:
        raise CollectorError(
            f"Binance Vision checksum mismatch for {symbol} {month}"
        )
    rows = aggregate_aggtrades_zip(payload, symbol=symbol, base_asset=base_asset)
    return rows, ArchiveManifestEntry(symbol.upper(), month, "monthly", url, observed)


def fetch_daily_aggtrades(
    *,
    symbol: str,
    base_asset: str,
    day: str,
    expected_sha256: str,
    fetcher: BytesFetcher = default_bytes_fetcher,
) -> tuple[list[dict[str, Any]], ArchiveManifestEntry]:
    """Download one bounded daily tick archive for the equivalence diagnostic."""

    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
    url = daily_aggtrades_url(symbol, day)
    payload = fetcher(url)
    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected_sha256:
        raise CollectorError(f"Binance Vision checksum mismatch for {symbol} {day}")
    rows = aggregate_aggtrades_zip(
        payload, symbol=symbol, base_asset=base_asset, cadence="daily"
    )
    return rows, ArchiveManifestEntry(symbol.upper(), day, "daily", url, observed)
