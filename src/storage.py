"""SQLite + JSONL persistence for the agent.

Tables (kept intentionally small, no ORM):
- decisions       — every Decision record produced by the engine
- orders          — every ExecutionResult (incl. dry-run logs)
- positions       — latest known position per symbol
- pnl_snapshots   — periodic PnL snapshots
- errors          — structured error records
- cycles          — one row per agent loop iteration (with summary)

Mirroring JSONL files are written to `data/decisions.jsonl`, `data/trades.jsonl`
and `data/pnl.jsonl` for human-friendly auditing.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .config import get_settings
from .logger import get_logger
from .schemas import Decision, ExecutionResult, PnLSnapshot, PortfolioSnapshot
from .utils import utc_now_iso

logger = get_logger(__name__)
_LOCK = threading.Lock()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS decisions (
    id            TEXT PRIMARY KEY,
    at            TEXT NOT NULL,
    cycle_id      TEXT,
    symbol        TEXT NOT NULL,
    action        TEXT NOT NULL,
    final_score   REAL NOT NULL,
    confidence    REAL NOT NULL,
    suggested_size_usd REAL NOT NULL,
    approved_size_usd  REAL NOT NULL DEFAULT 0,
    regime        TEXT NOT NULL DEFAULT 'UNKNOWN',
    mode          TEXT NOT NULL DEFAULT 'dry_run',
    approved      INTEGER NOT NULL DEFAULT 0,
    rationale     TEXT,
    payload_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_at ON decisions(at);
CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON decisions(symbol);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL,
    decision_id   TEXT,
    mode          TEXT NOT NULL,
    status        TEXT NOT NULL,
    symbol        TEXT,
    action        TEXT,
    requested_size_usd REAL,
    filled_size_usd    REAL,
    fill_price    REAL,
    volume        REAL,
    fee           REAL,
    order_id      TEXT,
    error         TEXT,
    payload_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_at ON orders(at);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);

CREATE TABLE IF NOT EXISTS positions (
    symbol            TEXT PRIMARY KEY,
    quantity          REAL NOT NULL,
    avg_entry_price   REAL NOT NULL,
    market_price      REAL NOT NULL,
    notional_usd      REAL NOT NULL,
    unrealized_pnl_usd REAL NOT NULL,
    realized_pnl_usd  REAL NOT NULL,
    updated_at        TEXT NOT NULL,
    opened_at         TEXT
);

CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL,
    realized_usd  REAL NOT NULL,
    unrealized_usd REAL NOT NULL,
    net_usd       REAL NOT NULL,
    equity_usd    REAL NOT NULL,
    drawdown_pct  REAL NOT NULL,
    source        TEXT NOT NULL,
    note          TEXT,
    payload_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS errors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL,
    where_label   TEXT NOT NULL,
    message       TEXT NOT NULL,
    context_json  TEXT
);

CREATE TABLE IF NOT EXISTS cycles (
    id            TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    duration_ms   INTEGER,
    mode          TEXT NOT NULL,
    symbols_seen  INTEGER NOT NULL DEFAULT 0,
    decisions     INTEGER NOT NULL DEFAULT 0,
    approved      INTEGER NOT NULL DEFAULT 0,
    errors        INTEGER NOT NULL DEFAULT 0,
    summary_json  TEXT
);
"""


def _resolve(path: str) -> Path:
    return get_settings().absolute_path(path)


def _connect() -> sqlite3.Connection:
    db_path = _resolve(get_settings().env.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def _ensure_position_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migration: add ``opened_at`` to legacy ``positions`` tables.

    Sqlite's ``CREATE TABLE IF NOT EXISTS`` is a no-op when the table already
    exists with the old shape, so we need an explicit ``ALTER TABLE``. The
    statement is wrapped in a try/except because ``ADD COLUMN`` raises on
    duplicate columns and there is no portable ``IF NOT EXISTS`` for it.
    """
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(positions)")}
    except sqlite3.DatabaseError:
        return
    if cols and "opened_at" not in cols:
        try:
            conn.execute("ALTER TABLE positions ADD COLUMN opened_at TEXT")
        except sqlite3.OperationalError:
            pass


def init_db() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_position_columns(conn)
        conn.commit()


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def write_decision(decision: Decision) -> None:
    init_db()
    payload = decision.model_dump(mode="json")
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO decisions
            (id, at, cycle_id, symbol, action, final_score, confidence,
             suggested_size_usd, approved_size_usd, regime, mode, approved,
             rationale, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.id,
                decision.at,
                decision.cycle_id,
                decision.symbol,
                decision.action,
                decision.final_score,
                decision.confidence,
                decision.suggested_size_usd,
                decision.approved_size_usd,
                decision.regime,
                decision.mode,
                1 if decision.risk.approved else 0,
                decision.rationale,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    _append_jsonl(_resolve(get_settings().env.decisions_log_path), payload)


def write_order(decision_id: str | None, result: ExecutionResult) -> None:
    init_db()
    payload = result.model_dump(mode="json")
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO orders
            (at, decision_id, mode, status, symbol, action, requested_size_usd,
             filled_size_usd, fill_price, volume, fee, order_id, error, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.at,
                decision_id,
                result.mode,
                result.status,
                result.symbol,
                result.action,
                result.requested_size_usd,
                result.filled_size_usd,
                result.fill_price,
                result.volume,
                result.fee,
                result.order_id,
                result.error,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    _append_jsonl(_resolve(get_settings().env.trades_log_path), payload)


def upsert_portfolio(snapshot: PortfolioSnapshot) -> None:
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM positions")
        for pos in snapshot.positions:
            conn.execute(
                """
                INSERT INTO positions
                (symbol, quantity, avg_entry_price, market_price, notional_usd,
                 unrealized_pnl_usd, realized_pnl_usd, updated_at, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pos.symbol,
                    pos.quantity,
                    pos.avg_entry_price,
                    pos.market_price,
                    pos.notional_usd,
                    pos.unrealized_pnl_usd,
                    pos.realized_pnl_usd,
                    snapshot.as_of,
                    pos.opened_at,
                ),
            )
        conn.commit()


def write_pnl(snapshot: PnLSnapshot) -> None:
    init_db()
    payload = snapshot.model_dump(mode="json")
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO pnl_snapshots
            (at, realized_usd, unrealized_usd, net_usd, equity_usd, drawdown_pct,
             source, note, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.as_of,
                snapshot.realized_usd,
                snapshot.unrealized_usd,
                snapshot.net_usd,
                snapshot.equity_usd,
                snapshot.drawdown_pct,
                snapshot.source,
                snapshot.note,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    _append_jsonl(_resolve(get_settings().env.pnl_log_path), payload)


def record_error(where: str, message: str, context: dict[str, Any] | None = None) -> None:
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO errors (at, where_label, message, context_json) VALUES (?, ?, ?, ?)",
            (utc_now_iso(), where, message, json.dumps(context or {}, ensure_ascii=False)),
        )
        conn.commit()


def start_cycle(cycle_id: str, mode: str) -> None:
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO cycles (id, started_at, mode) VALUES (?, ?, ?)",
            (cycle_id, utc_now_iso(), mode),
        )
        conn.commit()


def finish_cycle(
    cycle_id: str,
    duration_ms: int,
    symbols_seen: int,
    decisions: int,
    approved: int,
    errors: int,
    summary: dict[str, Any] | None = None,
) -> None:
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            UPDATE cycles
               SET finished_at = ?, duration_ms = ?, symbols_seen = ?,
                   decisions = ?, approved = ?, errors = ?, summary_json = ?
             WHERE id = ?
            """,
            (
                utc_now_iso(),
                duration_ms,
                symbols_seen,
                decisions,
                approved,
                errors,
                json.dumps(summary or {}, ensure_ascii=False),
                cycle_id,
            ),
        )
        conn.commit()


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def fetch_recent_decisions(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()
    return _rows_to_dicts(rows)


def fetch_recent_orders(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()
    return _rows_to_dicts(rows)


def fetch_recent_errors(limit: int = 20) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM errors ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()
    return _rows_to_dicts(rows)


def fetch_recent_pnl(limit: int = 200) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pnl_snapshots ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()
    return _rows_to_dicts(rows)


def fetch_recent_cycles(limit: int = 200) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cycles ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return _rows_to_dicts(rows)


def fetch_positions() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM positions ORDER BY symbol").fetchall()
    return _rows_to_dicts(rows)


def db_healthcheck() -> dict[str, Any]:
    try:
        init_db()
        with _connect() as conn:
            counts = {}
            for table in ("decisions", "orders", "positions", "pnl_snapshots", "errors", "cycles"):
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            return {"ok": True, "counts": counts}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


__all__ = [
    "init_db",
    "write_decision",
    "write_order",
    "upsert_portfolio",
    "write_pnl",
    "record_error",
    "start_cycle",
    "finish_cycle",
    "fetch_recent_decisions",
    "fetch_recent_orders",
    "fetch_recent_errors",
    "fetch_recent_pnl",
    "fetch_recent_cycles",
    "fetch_positions",
    "db_healthcheck",
]
