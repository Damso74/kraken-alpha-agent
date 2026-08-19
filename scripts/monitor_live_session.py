"""Real-time CLI dashboard for an active option-D live session.

Refreshes every ``--refresh-seconds`` (default 5s) and prints, on a
single coloured terminal pane:

- Cumulative session PnL (realized + unrealized) since startup
- Distance to the ``-5.00 USD`` kill switch
- Open positions with entry price, current mark, per-position PnL
- Trades count + live win rate over the session
- Cumulative fees burned
- Current CEST wall clock + time remaining until the 21:55 flatten cut-off

All data is pulled from Kraken Futures via the existing
:mod:`src.futures_kraken_cli` wrapper (read-only endpoints: ``accounts``,
``positions``, optional ``fills``). The monitor never places orders.

Usage (PowerShell, separate terminal)::

    .\\.venv\\Scripts\\Activate.ps1
    $env:KRAKEN_FUTURES_API_KEY = "<read-only futures key>"
    $env:KRAKEN_FUTURES_API_SECRET = "<read-only secret>"
    python scripts/monitor_live_session.py --threshold-usd -5
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import futures_kraken_cli  # noqa: E402
from src.logger import get_logger, setup_logging  # noqa: E402

logger = get_logger("monitor_live_session")

# ANSI colour helpers — kept minimal so Windows powershell renders OK.
ANSI = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "white": "\x1b[37m",
}

_CEST_OFFSET_SECONDS = 2 * 3600


@dataclass
class SessionState:
    started_at_utc: datetime
    baseline_realized: float
    baseline_unrealized: float
    threshold_usd: float
    cest_cutoff_hour: int = 21
    cest_cutoff_minute: int = 55


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _cest_now(now_utc: datetime | None = None) -> datetime:
    now_utc = now_utc or _now_utc()
    return datetime.fromtimestamp(
        now_utc.timestamp() + _CEST_OFFSET_SECONDS, tz=UTC
    )


def _coloured(text: str, colour: str, *, bold: bool = False) -> str:
    if not sys.stdout.isatty():
        return text
    prefix = ANSI.get(colour, "")
    if bold:
        prefix = ANSI["bold"] + prefix
    return f"{prefix}{text}{ANSI['reset']}"


def _fetch_accounts() -> dict[str, Any]:
    result = futures_kraken_cli.run_futures_cli(["accounts"], timeout=15)
    if not result.ok or not isinstance(result.stdout_json, dict):
        return {"_error": result.stderr or result.status}
    return result.stdout_json


def _fetch_positions() -> dict[str, Any]:
    result = futures_kraken_cli.fetch_open_positions()
    if not result.ok or not isinstance(result.stdout_json, dict):
        return {"_error": result.stderr or result.status}
    return result.stdout_json


def _fetch_fills() -> dict[str, Any]:
    result = futures_kraken_cli.run_futures_cli(["fills"], timeout=15)
    if not result.ok or not isinstance(result.stdout_json, dict):
        return {"_error": result.stderr or result.status}
    return result.stdout_json


def _aggregate_pnl(accounts_payload: dict[str, Any]) -> tuple[float, float]:
    """Return ``(realized, unrealized)`` USD from the accounts payload."""
    realized = 0.0
    unrealized = 0.0
    accounts = accounts_payload.get("accounts") if isinstance(accounts_payload, dict) else None
    if isinstance(accounts, dict):
        for wallet in accounts.values():
            if not isinstance(wallet, dict):
                continue
            realized += float(wallet.get("balance") or 0.0)
            unrealized += float(wallet.get("pnl") or wallet.get("unrealizedFunding") or 0.0)
    return realized, unrealized


def _extract_positions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("openPositions") or payload.get("positions") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        out.append({
            "symbol": entry.get("symbol") or entry.get("pair") or "?",
            "side": entry.get("side") or "?",
            "size": float(entry.get("size") or entry.get("quantity") or 0.0),
            "entry": float(entry.get("price") or entry.get("avgEntryPrice") or 0.0),
            "mark": float(entry.get("markPrice") or entry.get("mark") or 0.0),
            "unrealized_pnl": float(entry.get("unrealizedPnL") or entry.get("pnl") or 0.0),
        })
    return out


def _extract_fills(payload: dict[str, Any], *, since_utc: datetime) -> list[dict[str, Any]]:
    raw = payload.get("fills") or payload.get("trades") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    since_ms = int(since_utc.timestamp() * 1000)
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        ts_raw = entry.get("fillTime") or entry.get("time") or entry.get("timestamp") or 0
        try:
            ts_ms = int(ts_raw)
            if ts_ms < 1_000_000_000_000:  # seconds → ms
                ts_ms *= 1000
        except (TypeError, ValueError):
            continue
        if ts_ms < since_ms:
            continue
        out.append({
            "symbol": entry.get("symbol") or "?",
            "side": (entry.get("side") or "").lower(),
            "size": float(entry.get("size") or entry.get("quantity") or 0.0),
            "price": float(entry.get("price") or 0.0),
            "fee": float(entry.get("fee") or entry.get("fees") or 0.0),
            "realized_pnl": float(entry.get("realizedPnL") or entry.get("pnl") or 0.0),
            "ts_ms": ts_ms,
        })
    return out


def _format_money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.4f}"


def _format_duration(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total < 0:
        return "(elapsed)"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


def _clear_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[2J\x1b[H")


def _render(state: SessionState) -> str:
    accounts = _fetch_accounts()
    positions_payload = _fetch_positions()
    fills_payload = _fetch_fills()
    realized, unrealized = _aggregate_pnl(accounts)
    net = realized + unrealized
    cumulative = (realized - state.baseline_realized) + (
        unrealized - state.baseline_unrealized
    )
    distance = cumulative - state.threshold_usd
    positions = _extract_positions(positions_payload)
    fills = _extract_fills(fills_payload, since_utc=state.started_at_utc)
    fees_total = sum(f["fee"] for f in fills)
    wins = sum(1 for f in fills if f["realized_pnl"] > 0 and f["side"] == "sell")
    losses = sum(1 for f in fills if f["realized_pnl"] < 0 and f["side"] == "sell")
    closed = wins + losses
    win_rate = (wins / closed * 100.0) if closed else 0.0

    now_utc = _now_utc()
    cest_now = _cest_now(now_utc)
    cest_cutoff = cest_now.replace(
        hour=state.cest_cutoff_hour,
        minute=state.cest_cutoff_minute,
        second=0,
        microsecond=0,
    )
    if cest_now > cest_cutoff:
        cest_cutoff = cest_cutoff + timedelta(days=1)
    time_to_cutoff = cest_cutoff - cest_now
    elapsed = now_utc - state.started_at_utc

    # Header
    parts: list[str] = []
    parts.append(_coloured(
        "═══════════ KRAKEN ALPHA AGENT — LIVE CRYPTO SESSION MONITOR ═══════════",
        "cyan", bold=True,
    ))
    parts.append(
        f"  started: {state.started_at_utc.isoformat(timespec='seconds')}  "
        f"elapsed: {_format_duration(elapsed)}"
    )
    parts.append(
        f"  CEST now: {cest_now.strftime('%H:%M:%S')}  "
        f"cutoff: {state.cest_cutoff_hour:02d}:{state.cest_cutoff_minute:02d}  "
        f"in: {_format_duration(time_to_cutoff)}"
    )

    # PnL block
    parts.append("")
    parts.append(_coloured("─── PnL ───", "white", bold=True))
    cum_colour = "green" if cumulative >= 0 else ("yellow" if cumulative > state.threshold_usd / 2 else "red")
    parts.append(
        f"  cumulative session PnL : {_coloured(_format_money(cumulative), cum_colour, bold=True)}  "
        f"(net wallet: {_format_money(net)})"
    )
    parts.append(
        f"  realized session       : {_format_money(realized - state.baseline_realized)}  "
        f"(baseline {_format_money(state.baseline_realized)})"
    )
    parts.append(
        f"  unrealized session     : {_format_money(unrealized - state.baseline_unrealized)}  "
        f"(baseline {_format_money(state.baseline_unrealized)})"
    )
    dist_colour = "green" if distance > 2.5 else ("yellow" if distance > 1.0 else "red")
    parts.append(
        f"  distance to kill switch: {_coloured(_format_money(distance), dist_colour, bold=True)}  "
        f"(threshold {_format_money(state.threshold_usd)})"
    )

    # Positions block
    parts.append("")
    parts.append(_coloured("─── Open positions ───", "white", bold=True))
    if "_error" in positions_payload:
        parts.append(_coloured(f"  positions query error: {positions_payload['_error']}", "red"))
    elif not positions:
        parts.append(_coloured("  (none)", "dim"))
    else:
        parts.append(
            "  " + " | ".join([
                f"{'symbol':<14}", f"{'side':<6}", f"{'size':>10}",
                f"{'entry':>10}", f"{'mark':>10}", f"{'pnl':>10}",
            ])
        )
        for p in positions:
            colour = "green" if p["unrealized_pnl"] >= 0 else "red"
            parts.append(
                "  " + " | ".join([
                    f"{p['symbol']:<14}",
                    f"{p['side']:<6}",
                    f"{p['size']:>10.4f}",
                    f"{p['entry']:>10.4f}",
                    f"{p['mark']:>10.4f}",
                    _coloured(f"{p['unrealized_pnl']:>+10.4f}", colour),
                ])
            )

    # Trades block
    parts.append("")
    parts.append(_coloured("─── Trades (this session) ───", "white", bold=True))
    if "_error" in fills_payload:
        parts.append(_coloured(f"  fills query error: {fills_payload['_error']}", "red"))
    else:
        parts.append(
            f"  fills={len(fills)}  closed={closed}  "
            f"wins={wins}  losses={losses}  "
            f"win_rate={win_rate:5.1f}%  "
            f"fees={_format_money(fees_total)}"
        )

    # Footer
    parts.append("")
    parts.append(_coloured(
        "  (read-only; refreshes every cycle; Ctrl+C to exit)",
        "dim",
    ))
    return "\n".join(parts)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read-only realtime monitor for an option-D live crypto session.",
    )
    p.add_argument(
        "--refresh-seconds",
        type=float,
        default=5.0,
        help="UI refresh interval (default 5s)",
    )
    p.add_argument(
        "--threshold-usd",
        type=float,
        default=-5.0,
        help="kill-switch threshold for the distance display (default -5.0)",
    )
    p.add_argument(
        "--cest-cutoff-hour",
        type=int,
        default=21,
        help="CEST hour at which the session is scheduled to stop (default 21)",
    )
    p.add_argument(
        "--cest-cutoff-minute",
        type=int,
        default=55,
        help="CEST minute at which the session is scheduled to stop (default 55)",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="render a single snapshot and exit (smoke check / CI)",
    )
    return p.parse_args()


def main() -> int:
    setup_logging()
    args = _parse_args()
    futures_key = (
        os.environ.get("KRAKEN_FUTURES_API_KEY")
        or os.environ.get("KRAKEN_API_KEY")
        or ""
    )
    if not futures_key:
        print(
            "KRAKEN_FUTURES_API_KEY (or KRAKEN_API_KEY) must be set; "
            "even read-only endpoints need an authenticated key.",
            file=sys.stderr,
        )
        return 2

    # Baseline snapshot
    initial = _fetch_accounts()
    if "_error" in initial:
        print(f"failed to fetch initial baseline: {initial['_error']}", file=sys.stderr)
        return 3
    realized0, unrealized0 = _aggregate_pnl(initial)
    state = SessionState(
        started_at_utc=_now_utc(),
        baseline_realized=realized0,
        baseline_unrealized=unrealized0,
        threshold_usd=float(args.threshold_usd),
        cest_cutoff_hour=int(args.cest_cutoff_hour),
        cest_cutoff_minute=int(args.cest_cutoff_minute),
    )

    if args.once:
        print(_render(state))
        return 0

    try:
        while True:
            _clear_screen()
            sys.stdout.write(_render(state))
            sys.stdout.write("\n")
            sys.stdout.flush()
            time.sleep(max(1.0, float(args.refresh_seconds)))
    except KeyboardInterrupt:
        print("\nmonitor stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
