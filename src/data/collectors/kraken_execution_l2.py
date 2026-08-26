"""Fail-closed public Kraken Futures L2/trade collector for H-EXE-001.

The module contains no authentication or order-entry surface.  It records the
public ``book`` and ``trade`` feeds with exchange, wall-clock and monotonic
timestamps.  A sequence gap invalidates the session immediately; the caller
must reconnect and wait for fresh snapshots rather than silently repairing it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KRAKEN_FUTURES_WS_URL = "wss://futures.kraken.com/ws/v1"
SCHEMA_VERSION = "h-exe-001-v1"


class ExecutionCollectorError(RuntimeError):
    """Base exception for the H-EXE-001 collector."""


class SequenceGapError(ExecutionCollectorError):
    """Raised when a public feed no longer has a contiguous sequence."""


class StorageCapExceeded(ExecutionCollectorError):
    """Raised before the configured append-only storage budget is exceeded."""


class RecoverableConnectionError(ExecutionCollectorError):
    """Public transport failure after zero or more successfully parsed messages."""

    def __init__(self, message: str, *, messages_received: int = 0) -> None:
        super().__init__(message)
        self.messages_received = int(messages_received)


class GlobalStorageBudget:
    """One fail-closed byte budget shared across writers under an output root."""

    def __init__(self, root: Path, storage_cap_bytes: int) -> None:
        if storage_cap_bytes <= 0:
            raise ValueError("storage_cap_bytes must be positive")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.storage_cap_bytes = int(storage_cap_bytes)
        self.preexisting_bytes = sum(
            path.stat().st_size for path in self.root.rglob("*") if path.is_file()
        )
        self.reserved_session_bytes = 0
        self._lock = threading.Lock()

    def reserve(self, byte_count: int) -> None:
        if byte_count < 0:
            raise ValueError("byte_count cannot be negative")
        with self._lock:
            projected = self.preexisting_bytes + self.reserved_session_bytes + byte_count
            if projected > self.storage_cap_bytes:
                raise StorageCapExceeded(
                    f"write would exceed global storage cap {self.storage_cap_bytes} bytes"
                )
            self.reserved_session_bytes += byte_count

    @property
    def projected_bytes(self) -> int:
        return self.preexisting_bytes + self.reserved_session_bytes


def _positive_float(value: Any, *, label: str, allow_zero: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionCollectorError(f"invalid {label}: {value!r}") from exc
    minimum_ok = parsed >= 0 if allow_zero else parsed > 0
    if not math.isfinite(parsed) or not minimum_ok:
        raise ExecutionCollectorError(f"invalid {label}: {value!r}")
    return parsed


def _positive_int(value: Any, *, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionCollectorError(f"invalid {label}: {value!r}") from exc
    if parsed <= 0:
        raise ExecutionCollectorError(f"invalid {label}: {value!r}")
    return parsed


@dataclass
class BookState:
    """In-memory L2 book reconstructed from a snapshot and contiguous deltas."""

    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)

    def replace(self, bids: Sequence[Any], asks: Sequence[Any]) -> None:
        self.bids = self._levels(bids, label="bid")
        self.asks = self._levels(asks, label="ask")
        self._validate_crossed()

    @staticmethod
    def _levels(raw: Sequence[Any], *, label: str) -> dict[float, float]:
        levels: dict[float, float] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                raise ExecutionCollectorError(f"{label} level is not an object")
            price = _positive_float(item.get("price"), label=f"{label} price")
            qty = _positive_float(item.get("qty"), label=f"{label} qty")
            levels[price] = qty
        if not levels:
            raise ExecutionCollectorError(f"empty {label} snapshot")
        return levels

    def apply(self, side: str, price: Any, qty: Any) -> None:
        price_value = _positive_float(price, label="book delta price")
        qty_value = _positive_float(qty, label="book delta qty", allow_zero=True)
        if side == "buy":
            target = self.bids
        elif side == "sell":
            target = self.asks
        else:
            raise ExecutionCollectorError(f"invalid book side: {side!r}")
        if qty_value == 0:
            target.pop(price_value, None)
        else:
            target[price_value] = qty_value
        if not self.bids or not self.asks:
            raise ExecutionCollectorError("book delta removed an entire side")
        self._validate_crossed()

    def _validate_crossed(self) -> None:
        if self.bids and self.asks and max(self.bids) >= min(self.asks):
            raise ExecutionCollectorError("reconstructed book is crossed or locked")

    def top(self) -> dict[str, float]:
        if not self.bids or not self.asks:
            raise ExecutionCollectorError("book snapshot required before top-of-book")
        bid = max(self.bids)
        ask = min(self.asks)
        return {
            "bid": bid,
            "bid_qty": self.bids[bid],
            "ask": ask,
            "ask_qty": self.asks[ask],
            "mid": (bid + ask) / 2.0,
            "spread_bps": (ask - bid) / ((bid + ask) / 2.0) * 10_000.0,
        }

    def depth(self, levels: int = 5) -> dict[str, float]:
        if levels <= 0:
            raise ValueError("levels must be positive")
        bid_qty = sum(qty for _, qty in sorted(self.bids.items(), reverse=True)[:levels])
        ask_qty = sum(qty for _, qty in sorted(self.asks.items())[:levels])
        total = bid_qty + ask_qty
        return {
            "bid_depth": bid_qty,
            "ask_depth": ask_qty,
            "imbalance": (bid_qty - ask_qty) / total if total else 0.0,
        }

    def serialized_levels(self) -> dict[str, list[dict[str, float]]]:
        """Return a complete deterministic snapshot for replay provenance."""
        return {
            "bids": [
                {"price": price, "qty": qty}
                for price, qty in sorted(self.bids.items(), reverse=True)
            ],
            "asks": [
                {"price": price, "qty": qty}
                for price, qty in sorted(self.asks.items())
            ],
        }


class RotatingGzipJsonlWriter:
    """Append-only gzip JSONL writer with UTC-day/size rotation and hard cap.

    Files are never deleted to make room.  The cap is conservative: it charges
    each uncompressed JSON line against the remaining budget even though gzip
    normally uses less disk space.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_file_bytes: int = 256 * 1024 * 1024,
        storage_cap_bytes: int = 100 * 1024 * 1024 * 1024,
        storage_budget: GlobalStorageBudget | None = None,
    ) -> None:
        if max_file_bytes <= 0 or storage_cap_bytes <= 0:
            raise ValueError("writer limits must be positive")
        if max_file_bytes > storage_cap_bytes:
            raise ValueError("max_file_bytes cannot exceed storage_cap_bytes")
        self.root = Path(root)
        self.max_file_bytes = int(max_file_bytes)
        self.storage_cap_bytes = int(storage_cap_bytes)
        self.root.mkdir(parents=True, exist_ok=True)
        self.storage_budget = storage_budget or GlobalStorageBudget(
            self.root, self.storage_cap_bytes
        )
        if self.storage_budget.storage_cap_bytes != self.storage_cap_bytes:
            raise ValueError("writer and shared storage cap must match")
        self._current_day: str | None = None
        self._current_uncompressed_bytes = 0
        self._handle: Any = None
        self._path: Path | None = None
        self._files: list[Path] = []
        self.rows_written = 0

    @property
    def files(self) -> tuple[Path, ...]:
        return tuple(self._files)

    def _next_path(self, day: str) -> Path:
        day_dir = self.root / day
        day_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(day_dir.glob("part-*.jsonl.gz"))
        part = 0
        if existing:
            try:
                part = max(int(path.name.split("-")[1].split(".")[0]) for path in existing) + 1
            except (IndexError, ValueError) as exc:
                raise ExecutionCollectorError("invalid existing rotation filename") from exc
        return day_dir / f"part-{part:05d}.jsonl.gz"

    def _rotate(self, day: str) -> None:
        self.close_current()
        self._path = self._next_path(day)
        self._handle = gzip.open(self._path, mode="at", encoding="utf-8", newline="\n")
        self._files.append(self._path)
        self._current_day = day
        self._current_uncompressed_bytes = 0

    def append(self, record: Mapping[str, Any]) -> None:
        exchange_ms = _positive_int(record.get("exchange_timestamp_ms"), label="exchange time")
        day = datetime.fromtimestamp(exchange_ms / 1000.0, tz=UTC).date().isoformat()
        line = json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
        encoded_bytes = len(line.encode("utf-8"))
        self.storage_budget.reserve(encoded_bytes)
        if (
            self._handle is None
            or day != self._current_day
            or self._current_uncompressed_bytes + encoded_bytes > self.max_file_bytes
        ):
            self._rotate(day)
        self._handle.write(line)
        self._handle.flush()
        self._current_uncompressed_bytes += encoded_bytes
        self.rows_written += 1

    def close_current(self) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._path = None

    def close(self) -> None:
        self.close_current()

    def manifest(self) -> dict[str, Any]:
        self.close_current()
        files = []
        for path in self._files:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append(
                {
                    "path": str(path.resolve()),
                    "bytes": path.stat().st_size,
                    "sha256": digest,
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "rows_written": self.rows_written,
            "storage_cap_bytes": self.storage_cap_bytes,
            "global_storage_root": str(self.storage_budget.root.resolve()),
            "global_preexisting_bytes": self.storage_budget.preexisting_bytes,
            "global_projected_bytes": self.storage_budget.projected_bytes,
            "max_file_bytes": self.max_file_bytes,
            "files": files,
        }


MarketEventHandler = Callable[[dict[str, Any], BookState], None]
ConnectionResetHandler = Callable[[], None]


class KrakenExecutionL2Collector:
    """Parse, validate and persist public Kraken L2/trade feed messages."""

    def __init__(
        self,
        product_ids: Sequence[str],
        *,
        writer: RotatingGzipJsonlWriter | None = None,
        on_market_event: MarketEventHandler | None = None,
        on_connection_reset: ConnectionResetHandler | None = None,
    ) -> None:
        products = tuple(dict.fromkeys(str(item) for item in product_ids))
        if not products or any(not item.startswith("PF_") for item in products):
            raise ValueError("product_ids must contain Kraken perpetual symbols")
        self.product_ids = products
        self.writer = writer
        self.on_market_event = on_market_event
        self.on_connection_reset = on_connection_reset
        self.books = {product: BookState() for product in products}
        self._sequences: dict[tuple[str, str], int] = {}
        self.valid = True
        self.invalid_reason: str | None = None
        self.connections_started = 0
        self.connection_errors: list[str] = []
        self.first_exchange_timestamp_ms: int | None = None
        self.last_exchange_timestamp_ms: int | None = None

    def begin_connection(self) -> None:
        """Reset feed state so a reconnect must provide fresh snapshots."""
        if not self.valid:
            raise ExecutionCollectorError(f"collector session is invalid: {self.invalid_reason}")
        self._sequences.clear()
        self.books = {product: BookState() for product in self.product_ids}
        self.connections_started += 1
        if self.on_connection_reset is not None:
            self.on_connection_reset()

    def subscriptions(self) -> tuple[dict[str, Any], ...]:
        return (
            {"event": "subscribe", "feed": "book", "product_ids": list(self.product_ids)},
            {"event": "subscribe", "feed": "trade", "product_ids": list(self.product_ids)},
        )

    def _fail(self, reason: str, exc_type: type[ExecutionCollectorError]) -> None:
        self.valid = False
        self.invalid_reason = reason
        raise exc_type(reason)

    def _sequence(self, feed: str, product: str, seq: Any, *, snapshot: bool) -> int:
        value = _positive_int(seq, label=f"{feed} sequence")
        key = (feed, product)
        previous = self._sequences.get(key)
        if snapshot:
            self._sequences[key] = value
            return value
        if previous is None:
            self._fail(f"{feed}/{product} delta received before snapshot", SequenceGapError)
        assert previous is not None
        if value != previous + 1:
            self._fail(
                f"{feed}/{product} sequence gap: expected {previous + 1}, got {value}",
                SequenceGapError,
            )
        self._sequences[key] = value
        return value

    @staticmethod
    def _envelope(
        *,
        event_type: str,
        product: str,
        sequence: int,
        exchange_timestamp_ms: int,
        received_wall_ns: int,
        received_monotonic_ns: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "event_type": event_type,
            "product_id": product,
            "sequence": sequence,
            "exchange_timestamp_ms": exchange_timestamp_ms,
            "received_wall_ns": received_wall_ns,
            "received_monotonic_ns": received_monotonic_ns,
            "observed_transport_lag_ms": received_wall_ns / 1_000_000 - exchange_timestamp_ms,
        }

    def _emit(self, event: dict[str, Any]) -> None:
        exchange_ms = int(event["exchange_timestamp_ms"])
        if self.first_exchange_timestamp_ms is None:
            self.first_exchange_timestamp_ms = exchange_ms
        self.last_exchange_timestamp_ms = max(
            exchange_ms, self.last_exchange_timestamp_ms or exchange_ms
        )
        if self.writer is not None:
            self.writer.append(event)
        if self.on_market_event is not None:
            self.on_market_event(event, self.books[event["product_id"]])

    def process_message(
        self,
        message: str | bytes | Mapping[str, Any],
        *,
        received_wall_ns: int | None = None,
        received_monotonic_ns: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.valid:
            raise ExecutionCollectorError(f"collector session is invalid: {self.invalid_reason}")
        wall_ns = time.time_ns() if received_wall_ns is None else int(received_wall_ns)
        monotonic_ns = (
            time.monotonic_ns() if received_monotonic_ns is None else int(received_monotonic_ns)
        )
        try:
            payload = json.loads(message) if isinstance(message, (str, bytes)) else dict(message)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._fail(f"invalid websocket JSON: {exc}", ExecutionCollectorError)
        if not isinstance(payload, Mapping):
            self._fail("websocket payload is not an object", ExecutionCollectorError)

        event_name = payload.get("event")
        if event_name == "error" or event_name in {"subscribed_failed", "unsubscribed_failed"}:
            self._fail(f"Kraken websocket error: {payload.get('message', event_name)}", ExecutionCollectorError)
        if event_name is not None:
            return []

        feed = str(payload.get("feed", ""))
        product = str(payload.get("product_id", ""))
        if product not in self.books:
            self._fail(f"unexpected product_id: {product!r}", ExecutionCollectorError)
        emitted: list[dict[str, Any]] = []

        if feed == "book_snapshot":
            seq = self._sequence("book", product, payload.get("seq"), snapshot=True)
            exchange_ms = _positive_int(payload.get("timestamp"), label="book timestamp")
            bids = payload.get("bids")
            asks = payload.get("asks")
            if not isinstance(bids, list) or not isinstance(asks, list):
                self._fail("book snapshot is missing bids/asks", ExecutionCollectorError)
            self.books[product].replace(bids, asks)
            event = self._envelope(
                event_type="book_snapshot",
                product=product,
                sequence=seq,
                exchange_timestamp_ms=exchange_ms,
                received_wall_ns=wall_ns,
                received_monotonic_ns=monotonic_ns,
            )
            event.update(self.books[product].top())
            event.update(self.books[product].depth())
            event.update(self.books[product].serialized_levels())
            emitted.append(event)
        elif feed == "book":
            seq = self._sequence("book", product, payload.get("seq"), snapshot=False)
            exchange_ms = _positive_int(payload.get("timestamp"), label="book timestamp")
            self.books[product].apply(
                str(payload.get("side", "")), payload.get("price"), payload.get("qty")
            )
            event = self._envelope(
                event_type="book_delta",
                product=product,
                sequence=seq,
                exchange_timestamp_ms=exchange_ms,
                received_wall_ns=wall_ns,
                received_monotonic_ns=monotonic_ns,
            )
            event.update(
                {
                    "changed_side": str(payload.get("side")),
                    "changed_price": float(payload["price"]),
                    "changed_qty": float(payload["qty"]),
                }
            )
            event.update(self.books[product].top())
            event.update(self.books[product].depth())
            emitted.append(event)
        elif feed == "trade_snapshot":
            trades = payload.get("trades")
            if not isinstance(trades, list):
                self._fail("trade snapshot is missing trades[]", ExecutionCollectorError)
            valid_trades = [item for item in trades if isinstance(item, Mapping)]
            if not valid_trades:
                return []
            ordered = sorted(valid_trades, key=lambda item: _positive_int(item.get("seq"), label="trade sequence"))
            self._sequences[("trade", product)] = _positive_int(
                ordered[-1].get("seq"), label="trade sequence"
            )
            for trade in ordered:
                emitted.append(self._trade_event(trade, product, wall_ns, monotonic_ns, snapshot=True))
        elif feed == "trade":
            seq = self._sequence("trade", product, payload.get("seq"), snapshot=False)
            emitted.append(
                self._trade_event(
                    payload, product, wall_ns, monotonic_ns, snapshot=False, sequence=seq
                )
            )
        else:
            self._fail(f"unexpected public feed: {feed!r}", ExecutionCollectorError)

        for event in emitted:
            self._emit(event)
        return emitted

    def _trade_event(
        self,
        trade: Mapping[str, Any],
        product: str,
        wall_ns: int,
        monotonic_ns: int,
        *,
        snapshot: bool,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        side = str(trade.get("side", ""))
        if side not in {"buy", "sell"}:
            self._fail(f"invalid trade side: {side!r}", ExecutionCollectorError)
        seq = sequence or _positive_int(trade.get("seq"), label="trade sequence")
        event = self._envelope(
            event_type="trade",
            product=product,
            sequence=seq,
            exchange_timestamp_ms=_positive_int(trade.get("time"), label="trade time"),
            received_wall_ns=wall_ns,
            received_monotonic_ns=monotonic_ns,
        )
        event.update(
            {
                "snapshot": snapshot,
                "uid": str(trade.get("uid", "")),
                "side": side,
                "trade_type": str(trade.get("type", "")),
                "price": _positive_float(trade.get("price"), label="trade price"),
                "qty": _positive_float(trade.get("qty"), label="trade qty"),
            }
        )
        return event


def run_public_shadow_stream(
    collector: KrakenExecutionL2Collector,
    *,
    duration_seconds: float,
    websocket_url: str = KRAKEN_FUTURES_WS_URL,
) -> int:
    """Collect one public connection for a bounded duration; never trade."""
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    try:
        from websockets.exceptions import WebSocketException
        from websockets.sync.client import connect
    except ImportError as exc:  # pragma: no cover - dependency is installed by uvicorn[standard]
        raise ExecutionCollectorError("websockets package is required for collection") from exc

    deadline = time.monotonic() + duration_seconds
    messages_received = 0
    collector.begin_connection()
    try:
        with connect(websocket_url, open_timeout=15, close_timeout=10) as websocket:
            for subscription in collector.subscriptions():
                websocket.send(json.dumps(subscription))
            last_ping = time.monotonic()
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now - last_ping >= 30:
                    websocket.ping()
                    last_ping = now
                timeout = min(1.0, max(0.01, deadline - now))
                try:
                    message = websocket.recv(timeout=timeout)
                except TimeoutError:
                    continue
                collector.process_message(message)
                messages_received += 1
    except (OSError, WebSocketException) as exc:
        raise RecoverableConnectionError(
            f"{type(exc).__name__}: {exc}", messages_received=messages_received
        ) from exc
    return messages_received
